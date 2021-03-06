import datetime
import re
import uuid
import xml.etree.ElementTree as ET
from xml.etree import ElementTree

from django.core.files.uploadedfile import UploadedFile
from django.template.loader import render_to_string

from casexml.apps.case import const
from casexml.apps.case.models import CommCareCase
from casexml.apps.phone.xml import get_case_xml
from corehq.apps.receiverwrapper.util import submit_form_locally
from corehq.apps.users.util import SYSTEM_USER_ID
from corehq.form_processor.exceptions import CaseNotFound
from corehq.form_processor.interfaces.dbaccessors import get_cached_case_attachment, CaseAccessors
from dimagi.utils.parsing import json_format_datetime

SYSTEM_FORM_XMLNS = 'http://commcarehq.org/case'

ALLOWED_CASE_IDENTIFIER_TYPES = [
    "contact_phone_number",
    "external_id",
]


def submit_case_blocks(case_blocks, domain, username="system", user_id="",
                       xmlns=SYSTEM_FORM_XMLNS, attachments=None,
                       form_id=None, form_extras=None, case_db=None):
    """
    Submits casexml in a manner similar to how they would be submitted from a phone.

    returns the UID of the resulting form.
    """
    attachments = attachments or {}
    now = json_format_datetime(datetime.datetime.utcnow())
    if not isinstance(case_blocks, basestring):
        case_blocks = ''.join(case_blocks)
    form_id = form_id or uuid.uuid4().hex
    form_xml = render_to_string('hqcase/xml/case_block.xml', {
        'xmlns': xmlns,
        'case_block': case_blocks,
        'time': now,
        'uid': form_id,
        'username': username,
        'user_id': user_id,
    })
    form_extras = form_extras or {}

    result = submit_form_locally(
        instance=form_xml,
        domain=domain,
        attachments=attachments,
        case_db=case_db,
        **form_extras
    )
    return result.xform, result.cases


def get_case_wrapper(data):
    from corehq.apps.commtrack.util import get_case_wrapper as commtrack_wrapper

    def pact_wrapper(data):
        if data['domain'] == 'pact' and data['type'] == 'cc_path_client':
            from pact.models import PactPatientCase
            return PactPatientCase

    wrapper_funcs = [pact_wrapper, commtrack_wrapper]

    wrapper = None
    for wf in wrapper_funcs:
        wrapper = wf(data)
        if wrapper is not None:
            break
    return wrapper


def _get_cases_by_domain_hq_user_id(domain, user_id, case_type, include_docs):
    return CommCareCase.view(
        'case_by_domain_hq_user_id_type/view',
        key=[domain, user_id, case_type],
        reduce=False,
        include_docs=include_docs
    ).all()


def get_case_by_domain_hq_user_id(domain, user_id, case_type):
    """
    Return the first case of case_type owned by user_id
    """
    cases = _get_cases_by_domain_hq_user_id(domain, user_id, case_type, include_docs=True)
    return cases[0] if cases else None


def get_case_id_by_domain_hq_user_id(domain, user_id, case_type):
    """
    Return the ID of the first case of case_type owned by user_id
    """
    rows = _get_cases_by_domain_hq_user_id(domain, user_id, case_type, include_docs=False)
    return rows[0]['id'] if rows else None


def get_case_by_identifier(domain, identifier):
    # circular import
    from corehq.apps.api.es import CaseES
    case_es = CaseES(domain)
    case_accessors = CaseAccessors(domain)

    def _query_by_type(i_type):
        q = case_es.base_query(
            terms={
                i_type: identifier,
            },
            fields=['_id', i_type],
            size=1
        )
        response = case_es.run_query(q)
        raw_docs = response['hits']['hits']
        if raw_docs:
            return case_accessors.get_case(raw_docs[0]['_id'])

    # Try by any of the allowed identifiers
    for identifier_type in ALLOWED_CASE_IDENTIFIER_TYPES:
        case = _query_by_type(identifier_type)
        if case is not None:
            return case

    # Try by case id
    try:
        case_by_id = case_accessors.get_case(identifier)
        if case_by_id.domain == domain:
            return case_by_id
    except (CaseNotFound, KeyError):
        pass

    return None


def make_creating_casexml(domain, case, new_case_id, new_parent_ids=None):
    new_parent_ids = new_parent_ids or {}
    old_case_id = case.case_id
    case.case_id = new_case_id
    local_move_back = {}
    for index in case.indices:
        new = new_parent_ids[index.referenced_id]
        old = index.referenced_id
        local_move_back[new] = old
        index.referenced_id = new
    try:
        case_block = get_case_xml(case, (const.CASE_ACTION_CREATE, const.CASE_ACTION_UPDATE), version='2.0')
        case_block, attachments = _process_case_block(domain, case_block, case.case_attachments, old_case_id)
    finally:
        case.case_id = old_case_id
        for index in case.indices:
            index.referenced_id = local_move_back[index.referenced_id]
    return case_block, attachments


def _process_case_block(domain, case_block, attachments, old_case_id):
    def get_namespace(element):
        m = re.match('\{.*\}', element.tag)
        return m.group(0)[1:-1] if m else ''

    def local_attachment(attachment, old_case_id, tag):
        mime = attachment['server_mime']
        size = attachment['attachment_size']
        src = attachment['attachment_src']
        cached_attachment = get_cached_case_attachment(domain, old_case_id, tag)
        attachment_meta, attachment_stream = cached_attachment.get()
        return UploadedFile(attachment_stream, src, size=size, content_type=mime)

    # Remove namespace because it makes looking up tags a pain
    root = ET.fromstring(case_block)
    xmlns = get_namespace(root)
    case_block = re.sub(' xmlns="[^"]+"', '', case_block, count=1)

    root = ET.fromstring(case_block)
    tag = "attachment"
    xml_attachments = root.find(tag)
    ret_attachments = {}

    if xml_attachments:
        for attach in xml_attachments:
            attach.attrib['from'] = 'local'
            attach.attrib['src'] = attachments[attach.tag]['attachment_src']
            ret_attachments[attach.attrib['src']] = local_attachment(attachments[attach.tag], old_case_id, attach.tag)

    # Add namespace back in without { } added by ET
    root.attrib['xmlns'] = xmlns
    return ET.tostring(root), ret_attachments


def submit_case_block_from_template(domain, template, context, xmlns=None, user_id=None):
    case_block = render_to_string(template, context)
    # Ensure the XML is formatted properly
    # An exception is raised if not
    case_block = ElementTree.tostring(ElementTree.XML(case_block))

    user_id = user_id or SYSTEM_USER_ID
    kwargs = {}
    if xmlns:
        kwargs['xmlns'] = xmlns
    submit_case_blocks(case_block, domain, user_id=user_id, **kwargs)


def update_case(domain, case_id, case_properties=None, close=False, xmlns=None):
    """
    Updates or closes a case (or both) by submitting a form.
    domain - the case's domain
    case_id - the case's id
    case_properties - to update the case, pass in a dictionary of {name1: value1, ...}
                      to ignore case updates, leave this argument out
    close - True to close the case, False otherwise
    xmlns - pass in an xmlns to use it instead of the default
    """
    context = {
        'case_id': case_id,
        'date_modified': json_format_datetime(datetime.datetime.utcnow()),
        'user_id': SYSTEM_USER_ID,
        'case_properties': case_properties,
        'close': close,
    }
    submit_case_block_from_template(domain, 'hqcase/xml/update_case.xml', context, xmlns=xmlns)
