from corehq.apps.app_manager.dbaccessors import get_all_built_app_ids_and_versions
from corehq.apps.app_manager.models import Application
from corehq.apps.data_dictionary.models import CaseType, CaseProperty
from corehq.apps.export.const import PROPERTY_TAG_UPDATE
from corehq.apps.export.models.new import (
    CaseExportDataSchema, ExportDataSchema, ExportGroupSchema, ExportItem, MAIN_TABLE,
    CASE_HISTORY_TABLE, ScalarItem, PathNode, PARENT_CASE_TABLE
)


def generate_export_schema_from_data_dictionary(domain, case_type):
    schema = CaseExportDataSchema(domain=domain, case_type=case_type)
    properties = CaseProperty.objects.filter(case_type__domain=domain, case_type__name=case_type)
    group_schema = ExportGroupSchema(
        path=MAIN_TABLE,
        last_occurrences={},
    )
    history_group_schema = ExportGroupSchema(
        path=CASE_HISTORY_TABLE,
        last_occurrences={},
    )

    for prop in properties:
        group_schema.items.append(ScalarItem(
            path=[PathNode(name=prop.name)],
            label=prop.name,
            inferred=not prop.deprecated
        ))
        if prop in KNOWN_CASE_PROPERTIES:
            path_node = PathNode(name="updated_unknown_properties")
        else:
            path_node = PathNode(name="updated_known_properties")
        history_group_schema.items.append(ScalarItem(
            path=CASE_HISTORY_TABLE.extend([
                path_node,
                PathNode(name=prop.name)
            ]),
            label=prop.name,
            tag=PROPERTY_TAG_UPDATE
        ))

    schema.group_schemas.append(group_schema)
    schema.group_schemas.append(history_group_schema)
    parent_schema.extend(_generate_parent_table(domain, case_type))

    return schema


def _generate_parent_table(domain, case_type):
    app_build_verions = get_all_built_app_ids_and_versions(domain)
    # sort in reverse order
    app_build_versions = sorted(lambda x, y: x.version > y.version, app_build_versions)
    app_build_ids = [build.build_id for build in app_build_versions]

    for app_doc in iter_docs(Application.get_db(), app_build_ids, chunksize=10):
        parent_types, _ = (
            ParentCasePropertyBuilder(app)
            .get_parent_types_and_contributed_properties(case_type)
        )
        if any(map(lambda relationship_tuple: relationship_tuple[1] == 'parent', parent_types)):
            return [schema.group_schemas.append(ExportGroupSchema(
                path=PARENT_CASE_TABLE,
                inferred=True,
            ))]

    return []
