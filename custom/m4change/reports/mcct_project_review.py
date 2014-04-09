from django.http import HttpResponse
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _

from jsonobject import DateTimeProperty
from corehq import Domain
from corehq.apps.commtrack.util import get_commtrack_location_id
from corehq.apps.locations.models import Location
from corehq.apps.reports.cache import request_cache
from corehq.apps.reports.filters.fixtures import AsyncLocationFilter
from corehq.apps.users.models import CommCareUser
from corehq.elastic import ES_URLS

from corehq.apps.reports.standard import CustomProjectReport
from corehq.apps.reports.standard import ProjectReport, ProjectReportParametersMixin, DatespanMixin
from corehq.apps.reports.datatables import DataTablesHeader, DataTablesColumn
from corehq.apps.reports.dont_use.fields import StrongFilterUsersField
from corehq.apps.reports.generic import ElasticProjectInspectionReport
from corehq.apps.reports.standard.monitoring import MultiFormDrilldownMixin
from corehq.elastic import es_query
from custom.m4change.constants import BOOKING_FORMS, FOLLOW_UP_FORMS, BOOKED_AND_UNBOOKED_DELIVERY_FORMS, IMMUNIZATION_FORMS, \
    REJECTION_REASON_DISPLAY_NAMES
from custom.m4change.models import McctStatus
from custom.m4change.reports import get_location_hierarchy_by_id
from custom.m4change.utils import get_case_by_id, get_user_by_id, get_property, get_form_ids_by_status
from custom.m4change.constants import EMPTY_FIELD
from custom.m4change.reports.tasks import m4change_all_rows_task


CASE_FORM_SCRIPT_FILTER_NAMESPACES = BOOKED_AND_UNBOOKED_DELIVERY_FORMS + IMMUNIZATION_FORMS


def _get_date_range(range):
    if range is not None:
        dates = str(range).split(_(" to "))
        return (dates[0], dates[1])
    return None


def _get_report_query(start_date, end_date, filtered_case_ids):
    return {
        "query": {
            "bool": {
                "must": [
                    {"range": {"form.meta.timeEnd": {"from": start_date, "to": end_date, "include_upper": False}}},
                    {"term": {"doc_type": "xforminstance"}},
                ],
                "should": [
                    {"terms": {"xmlns.exact": CASE_FORM_SCRIPT_FILTER_NAMESPACES}},
                    {"range": {"form.visits": {"gte": 1, "lte": 4}}}
                ]
            }
        },
        "filter": {
            "and": [
                {"not": {"missing": {"field": "form.case.@case_id"}}},
                {"terms": {"form.case.@case_id": filtered_case_ids}}
            ]
        }
    }


def calculate_form_data(self, form):
    try:
        case_id = form["form"]["case"]["@case_id"]
        case = get_case_by_id(case_id)
    except KeyError:
        case = EMPTY_FIELD

    amount_due = EMPTY_FIELD
    service_type = EMPTY_FIELD
    visits = form["form"].get("visits")
    form_id = form["_id"]
    location_name = EMPTY_FIELD
    location_parent_name = EMPTY_FIELD
    location_id = None

    if case is not EMPTY_FIELD:
        user_id = get_property(case, "user_id", EMPTY_FIELD)
        user = get_user_by_id(user_id)
        location_id = get_commtrack_location_id(user, Domain.get_by_name(self.domain))
    if location_id is not None:
        location = Location.get(location_id)
        location_name = location.name
        location_parent = location.parent
        location_parent_name = location_parent.name if location_parent is not None else EMPTY_FIELD

    if form["xmlns"] in IMMUNIZATION_FORMS:
        service_type = _("Immunization")
        amount_due = 1000
    elif form["xmlns"] in BOOKED_AND_UNBOOKED_DELIVERY_FORMS:
        service_type = _("Delivery")
        amount_due = 2000
    elif visits == "1":
        service_type = _("First Antenatal")
        amount_due = 1000
    elif visits == "2":
        service_type = _("Second Antenatal")
        amount_due = 300
    elif visits == "3":
        service_type = _("Third Antenatal")
        amount_due = 300
    elif visits == "4":
        service_type = _("Fourth Antenatal")
        amount_due = 400

    return {'case': case, 'service_type': service_type, 'location_name': location_name,
            'location_parent_name': location_parent_name, 'amount_due': amount_due, 'form_id': form_id}


class BaseReport(CustomProjectReport, ElasticProjectInspectionReport, ProjectReport,
                 ProjectReportParametersMixin, MultiFormDrilldownMixin, DatespanMixin):
        emailable = False
        exportable = True
        exportable_all = True
        asynchronous = True
        ajax_pagination = True
        include_inactive = True

        fields = [
            AsyncLocationFilter,
            'custom.m4change.fields.DateRangeField',
            'custom.m4change.fields.CaseSearchField'
        ]

        base_template = 'm4change/report.html'
        report_template_path = 'm4change/selectTemplate.html'
        filter_users_field_class = StrongFilterUsersField

        @property
        def es_results(self):
            if not getattr(self, 'es_response', None):
                self.es_query(paginated=True)
            return self.es_response

        @property
        def es_all_results(self):
            if not getattr(self, 'es_response', None):
                self.es_query(paginated=False)
            return self.es_response

        def _get_filtered_cases(self, start_date, end_date):
            location_id = self.request.GET.get("location_id")
            location_ids = get_location_hierarchy_by_id(location_id, self.domain)
            domain = Domain.get_by_name(self.domain)
            all_users = CommCareUser.by_domain(self.domain)
            matching_user_ids = []
            for user in all_users:
                if hasattr(user, "user_data") and user.user_data.get("CCT", None) == "true":
                    user_location_id = get_commtrack_location_id(user, domain)
                    if user_location_id in location_ids:
                        matching_user_ids.append(user._id)

            query = {
                "query": {
                    "range": {
                        "modified_on": {
                            "from": start_date,
                            "to": end_date,
                            "include_upper": False
                        }
                    }
                },
                "filter": {
                    "and": [
                        {"terms": {"user_id": matching_user_ids}}
                    ]
                }
            }

            case_search = self.request.GET.get("case_search", "")
            if len(case_search) > 0:
                query["filter"]["and"].append({
                    "regexp": {
                        "name.exact": ".*?%s.*?" % case_search
                    }
                })

            es_response = es_query(params={"domain.exact": self.domain}, q=query, es_url=ES_URLS.get('cases'))
            return [res['_source']['_id'] for res in es_response.get('hits', {}).get('hits', [])]

        @property
        def total_records(self):
            return int(self.es_results['hits']['total'])


class McctProjectReview(BaseReport):
    name = 'mCCT Project Review Page'
    slug = 'mcct_project_review_page'
    display_status = 'eligible'

    @property
    def headers(self):
        headers = DataTablesHeader(
            DataTablesColumn(_("Date of service"), prop_name="form.meta.timeEnd"),
            DataTablesColumn(_("Client Name"), sortable=False),
            DataTablesColumn(_("Service Type"), sortable=False),
            DataTablesColumn(_("Health Facility"), sortable=False),
            DataTablesColumn(_("Card No."), sortable=False),
            DataTablesColumn(_("LGA"), sortable=False),
            DataTablesColumn(_("Phone No."), sortable=False),
            DataTablesColumn(_("Amount"), sortable=False),
            DataTablesColumn(mark_safe('Status/Action  <a href="#" class="select-all btn btn-mini btn-inverse">all</a> '
                                       '<a href="#" class="select-none btn btn-mini btn-warning">none</a>'),
                                        sortable=False, span=3))
        return headers

    def es_query(self, paginated):
        if not getattr(self, 'es_response', None):
            range = self.request_params.get('range', None)
            start_date = None
            end_date = None
            if range is not None:
                dates = str(range).split(_(" to "))
                start_date = dates[0]
                end_date = dates[1]
            filtered_case_ids = self._get_filtered_cases(start_date, end_date)
            exclude_form_ids = [mcct_status.form_id for mcct_status in McctStatus.objects.filter(domain=self.domain)]
            q = _get_report_query(start_date, end_date, filtered_case_ids)

            if len(exclude_form_ids) > 0:
                q["filter"]["and"].append({"not": {"ids": {"values": exclude_form_ids}}})

            allforms = BOOKING_FORMS + FOLLOW_UP_FORMS + BOOKED_AND_UNBOOKED_DELIVERY_FORMS + IMMUNIZATION_FORMS
            xmlnss = filter(None, [form for form in allforms])
            if xmlnss:
                q["filter"]["and"].append({"terms": {"xmlns.exact": xmlnss}})

            modify_close = filter(None, [u'Modify/Close Client'])
            q["filter"]["and"].append({"not": {"terms": {"form.@name": modify_close}}})

            q["sort"] = self.get_sorting_block() \
                if self.get_sorting_block() else [{"form.meta.timeEnd" : {"order": "desc"}}]
            if paginated:
                self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'),
                                            start_at=self.pagination.start, size=self.pagination.count)
            else:
                self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'))
        return self.es_response

    @property
    def rows(self):
        return self.make_rows(self.es_results, with_checkbox=True)

    @property
    def get_all_rows(self):
        return self.make_rows(self.es_all_results, with_checkbox=False)

    def make_rows(self, es_results, with_checkbox):
        submissions = [res['_source'] for res in self.es_results.get('hits', {}).get('hits', [])]
        for form in submissions:
            data = calculate_form_data(self, form)
            row = [
                DateTimeProperty().wrap(form["form"]["meta"]["timeEnd"]).strftime("%Y-%m-%d"),
                get_property(data.get('case'), "full_name", EMPTY_FIELD),
                data.get('service_type'),
                data.get('location_name'),
                get_property(data.get('case'), "card_number", EMPTY_FIELD),
                data.get('location_parent_name'),
                get_property(data.get('case'), "phone_number", EMPTY_FIELD),
                data.get('amount_due')
            ]
            if with_checkbox:
                checkbox = mark_safe('<input type="checkbox" class="selected-element" '
                                     'data-bind="event: {change: updateSelection}" data-formid="%(form_id)s" '
                                     'data-caseid="%(case_id)s" data-servicetype="%(service_type)s"/>')
                row.append(checkbox % dict(form_id=data.get('form_id'), case_id=data.get('case_id'),
                                           service_type=data.get('service_type')))
            else:
                row.append(self.display_status)
            yield row

    @property
    def export_table(self):
        headers = self.headers
        headers.header.pop()
        headers.header.append(DataTablesColumn(_("Status"), sortable=False))
        table = headers.as_export_table
        export_rows = self.get_all_rows
        table.extend(export_rows)
        return [[self.export_sheet_name, table]]

    @property
    @request_cache("export")
    def export_response(self):
        self.request.datespan = None
        m4change_all_rows_task.delay(self.__class__, self.__getstate__())

        return HttpResponse()


class McctClientApprovalPage(McctProjectReview):
    name = 'mCCT client Approval Page'
    slug = 'mcct_client_approval_page'
    report_template_path = 'm4change/approveStatus.html'
    display_status = 'reviewed'

    def es_query(self, paginated):
        reviewed_form_ids = get_form_ids_by_status(self.domain, getattr(self, 'display_status', None))
        if len(reviewed_form_ids) > 0:
            if not getattr(self, 'es_response', None):
                date_tuple = _get_date_range(self.request_params.get('range', None))
                filtered_case_ids = self._get_filtered_cases(date_tuple[0], date_tuple[1])
                q = _get_report_query(date_tuple[0], date_tuple[1], filtered_case_ids)

                if len(reviewed_form_ids) > 0:
                    q["filter"]["and"].append({"ids": {"values": reviewed_form_ids}})

                q["sort"] = self.get_sorting_block() if self.get_sorting_block() else [{"form.meta.timeEnd" : {"order": "desc"}}]
                if paginated:
                    self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'),
                                                start_at=self.pagination.start, size=self.pagination.count)
                else:
                    self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'))
        else:
            self.es_response = {'hits': {'total': 0}}

        return self.es_response


class McctClientPaymentPage(McctClientApprovalPage):
    name = 'mCCT client Payment Page'
    slug = 'mcct_client_payment_page'
    report_template_path = 'm4change/paidStatus.html'
    display_status = 'approved'


class McctRejectedClientPage(McctClientApprovalPage):
    name = 'mCCT Rejected clients Page'
    slug = 'mcct_rejected_clients_page'
    report_template_path = 'm4change/activateStatus.html'
    display_status = 'rejected'

    @property
    def headers(self):
        headers = DataTablesHeader(
            DataTablesColumn(_("Date of service"), prop_name="form.meta.timeEnd"),
            DataTablesColumn(_("Client Name"), sortable=False),
            DataTablesColumn(_("Service Type"), sortable=False),
            DataTablesColumn(_("Health Facility"), sortable=False),
            DataTablesColumn(_("Card No."), sortable=False),
            DataTablesColumn(_("LGA"), sortable=False),
            DataTablesColumn(_("Phone No."), sortable=False),
            DataTablesColumn(_("Amount"), sortable=False),
            DataTablesColumn(_("Comment"), sortable=False),
            DataTablesColumn(_("User"), sortable=False))
        return headers

    def make_rows(self, es_results, with_checkbox):
        submissions = [res['_source'] for res in self.es_results.get('hits', {}).get('hits', [])]
        for form in submissions:
            data = calculate_form_data(self, form)
            try:
                status_data = McctStatus.objects.get(domain=self.domain, form_id=data.get('form_id'))
                reason = status_data.reason
            except McctStatus.DoesNotExist:
                reason = None
            row = [
                DateTimeProperty().wrap(form["form"]["meta"]["timeEnd"]).strftime("%Y-%m-%d %H:%M"),
                get_property(data.get('case'), "full_name", EMPTY_FIELD),
                data.get('service_type'),
                data.get('location_name'),
                get_property(data.get('case'), "card_number", EMPTY_FIELD),
                data.get('location_parent_name'),
                get_property(data.get('case'), "phone_number", EMPTY_FIELD),
                data.get('amount_due'),
                REJECTION_REASON_DISPLAY_NAMES[reason] if reason is not None else '',
                form["form"]["meta"]["username"]
            ]
            if not with_checkbox:
                row.insert(8, self.display_status)
            yield row

    @property
    def export_table(self):
        headers = self.headers
        headers.header.insert(8, DataTablesColumn("Status", sortable=False))
        table = headers.as_export_table
        export_rows = self.get_all_rows
        table.extend(export_rows)
        return [[self.export_sheet_name, table]]


class McctClientLogPage(McctProjectReview):
    name = 'mCCT client Log Page'
    slug = 'mcct_client_log_page'
    report_template_path = 'm4change/report_content.html'

    @property
    def headers(self):
        headers = DataTablesHeader(
            DataTablesColumn(_("Date of service"), prop_name="form.meta.timeEnd"),
            DataTablesColumn(_("Client Name"), sortable=False),
            DataTablesColumn(_("Service Type"), sortable=False),
            DataTablesColumn(_("Health Facility"), sortable=False),
            DataTablesColumn(_("Card No."), sortable=False),
            DataTablesColumn(_("LGA"), sortable=False),
            DataTablesColumn(_("Phone No."), sortable=False),
            DataTablesColumn(_("Amount"), sortable=False),
            DataTablesColumn(_("Status"), sortable=False),
            DataTablesColumn(_("Comment"), sortable=False),
            DataTablesColumn(_("User"), sortable=False))
        return headers

    def es_query(self, paginated):
        if not getattr(self, 'es_response', None):
            date_tuple = _get_date_range(self.request_params.get('range', None))
            filtered_case_ids = self._get_filtered_cases(date_tuple[0], date_tuple[1])
            q = _get_report_query(date_tuple[0], date_tuple[1], filtered_case_ids)

            allforms = BOOKING_FORMS + FOLLOW_UP_FORMS + BOOKED_AND_UNBOOKED_DELIVERY_FORMS + IMMUNIZATION_FORMS
            xmlnss = filter(None, [form for form in allforms])
            if xmlnss:
                q["filter"]["and"].append({"terms": {"xmlns.exact": xmlnss}})

            modify_close = filter(None, [u'Modify/Close Client'])
            q["filter"]["and"].append({"not": {"terms": {"form.@name": modify_close}}})

            q["sort"] = self.get_sorting_block() \
                if self.get_sorting_block() else [{"form.meta.timeEnd": {"order": "desc"}}]
            if paginated:
                self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'),
                                            start_at=self.pagination.start, size=self.pagination.count)
            else:
                self.es_response = es_query(params={"domain.exact": self.domain}, q=q, es_url=ES_URLS.get('forms'))
        return self.es_response

    def make_rows(self, es_results, with_checkbox):
        submissions = [res['_source'] for res in self.es_results.get('hits', {}).get('hits', [])]
        for form in submissions:
            data = calculate_form_data(self, form)
            try:
                status_data = McctStatus.objects.get(domain=self.domain, form_id=data.get('form_id'))
                status, reason = (status_data.status, status_data.reason)
            except McctStatus.DoesNotExist:
                status, reason = ('eligible', None)
            row = [
                DateTimeProperty().wrap(form["form"]["meta"]["timeEnd"]).strftime("%Y-%m-%d %H:%M"),
                get_property(data.get('case'), "full_name", EMPTY_FIELD),
                data.get('service_type'),
                data.get('location_name'),
                get_property(data.get('case'), "card_number", EMPTY_FIELD),
                data.get('location_parent_name'),
                get_property(data.get('case'), "phone_number", EMPTY_FIELD),
                data.get('amount_due'),
                status,
                REJECTION_REASON_DISPLAY_NAMES[reason] if reason is not None else '',
                form["form"]["meta"]["username"]
            ]
            yield row

    @property
    def export_table(self):
        table = self.headers.as_export_table
        export_rows = self.get_all_rows
        table.extend(export_rows)
        return [[self.export_sheet_name, table]]


class McctPaidClientsPage(McctClientApprovalPage):
    name = 'mCCT Paid clients Page'
    slug = 'mcct_paid_clients_page'
    report_template_path = 'm4change/activateStatus.html'
    display_status = 'paid'
