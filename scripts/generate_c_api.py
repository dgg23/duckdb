import os
import json
import re
import glob
import copy
from packaging.version import Version
from functools import reduce
from pathlib import Path

###
# DuckDB C API header generation
###
# This script generates the DuckDB C API headers.
#
# The script works by parsing the definition files in `src/include/duckdb/main/capi/header_generation`, which are then
# used to generate the 3 header files:
#
# The main C header. This is what to include when linking with DuckDB through the C API.
DUCKDB_HEADER_OUT_FILE = 'src/include/duckdb.h'
# The header to be included by DuckDB C extensions
DUCKDB_HEADER_EXT_OUT_FILE = 'src/include/duckdb_extension.h'
# An internal header for DuckDB extension C API
DUCKDB_HEADER_EXT_INTERNAL_OUT_FILE = 'src/include/duckdb/main/capi/extension_api.hpp'

# Whether the script allows functions with parameters without a comment explaining them
ALLOW_UNCOMMENTED_PARAMS = True

DUCKDB_EXT_API_VAR_NAME = 'duckdb_ext_api'
DUCKDB_EXT_API_STRUCT_TYPENAME = 'duckdb_ext_api_v0'

DEV_VERSION_TAG = 'dev'

# Define the extension struct
EXT_API_DEFINITION_PATTERN = 'src/include/duckdb/main/capi/header_generation/apis/v0/*/*.json'
EXT_API_EXCLUSION_FILE = 'src/include/duckdb/main/capi/header_generation/apis/v0/exclusion_list.json'

# The JSON files that define all available CAPI functions
CAPI_FUNCTION_DEFINITION_FILES = 'src/include/duckdb/main/capi/header_generation/functions/**/*.json'

# The original order of the function groups in the duckdb.h files. We maintain this for easier PR reviews.
# TODO: replace this with alphabetical ordering in a separate PR
ORIGINAL_FUNCTION_GROUP_ORDER = [
    'open_connect',
    'configuration',
    'query_execution',
    'result_functions',
    'safe_fetch_functions',
    'helpers',
    'date_time_timestamp_helpers',
    'hugeint_helpers',
    'unsigned_hugeint_helpers',
    'decimal_helpers',
    'prepared_statements',
    'bind_values_to_prepared_statements',
    'execute_prepared_statements',
    'extract_statements',
    'pending_result_interface',
    'value_interface',
    'logical_type_interface',
    'data_chunk_interface',
    'vector_interface',
    'validity_mask_functions',
    'scalar_functions',
    'aggregate_functions',
    'table_functions',
    'table_function_bind',
    'table_function_init',
    'table_function',
    'replacement_scans',
    'profiling_info',
    'appender',
    'table_description',
    'arrow_interface',
    'threading_information',
    'streaming_result_interface',
    'cast_functions',
]

# The file that forms the base for the header generation
BASE_HEADER_TEMPLATE = 'src/include/duckdb/main/capi/header_generation/header_base.hpp.template'
# The comment marking where this script will inject its contents
BASE_HEADER_CONTENT_MARK = '// DUCKDB_FUNCTIONS_ARE_GENERATED_HERE\n'


def HEADER(file):
    return f'''//===----------------------------------------------------------------------===//
//
//                         DuckDB
//
// {file}
//
//
//===----------------------------------------------------------------------===//
//
// !!!!!!!
// WARNING: this file is autogenerated by scripts/generate_c_api.py, manual changes will be overwritten
// !!!!!!!
'''


def COMMENT_HEADER(name):
    return f'''//===--------------------------------------------------------------------===//
// {name}
//===--------------------------------------------------------------------===//
'''


HELPER_MACROS = f'''
#ifdef __cplusplus
#define DUCKDB_EXTENSION_EXTERN_C_GUARD_OPEN  extern "C" {{
#define DUCKDB_EXTENSION_EXTERN_C_GUARD_CLOSE }}
#else
#define DUCKDB_EXTENSION_EXTERN_C_GUARD_OPEN
#define DUCKDB_EXTENSION_EXTERN_C_GUARD_CLOSE
#endif

#define DUCKDB_EXTENSION_GLUE_HELPER(x, y) x##y
#define DUCKDB_EXTENSION_GLUE(x, y)        DUCKDB_EXTENSION_GLUE_HELPER(x, y)
#define DUCKDB_EXTENSION_STR_HELPER(x)     #x
#define DUCKDB_EXTENSION_STR(x)            DUCKDB_EXTENSION_STR_HELPER(x)
#define DUCKDB_EXTENSION_SEMVER_STRING(major, minor, patch) "v" DUCKDB_EXTENSION_STR_HELPER(major) "." DUCKDB_EXTENSION_STR_HELPER(minor) "." DUCKDB_EXTENSION_STR_HELPER(patch)

'''

DUCKDB_H_HEADER = HEADER('duckdb.h')
DUCKDB_EXT_H_HEADER = HEADER('duckdb_extension.h')
DUCKDB_EXT_INTERNAL_H_HEADER = HEADER('extension_api.hpp')


# Loads the template for the header files to be generated
def fetch_header_template_main():
    # Read the base header
    with open(BASE_HEADER_TEMPLATE, 'r') as f:
        result = f.read()

    # Trim the base header
    header_mark = '// DUCKDB_START_OF_HEADER\n'
    if header_mark not in result:
        print(f"Could not find the header start mark: {header_mark}")
        exit(1)

    return result[result.find(header_mark) + len(header_mark) :]


def fetch_header_template_ext():
    return """#pragma once
        
#include "duckdb.h"

"""


# Parse the CAPI_FUNCTION_DEFINITION_FILES to get the full list of functions
def parse_capi_function_definitions():
    # Collect all functions
    function_files = glob.glob(CAPI_FUNCTION_DEFINITION_FILES, recursive=True)

    function_groups = []
    function_map = {}

    # Read functions
    for file in function_files:
        with open(file, 'r') as f:
            try:
                json_data = json.loads(f.read())
            except json.decoder.JSONDecodeError as err:
                print(f"Invalid JSON found in {file}: {err}")
                exit(1)

            function_groups.append(json_data)
            for function in json_data['entries']:
                if function['name'] in function_map:
                    print(f"Duplicate symbol found when parsing C API file {file}: {function['name']}")
                    exit(1)

                function['group'] = json_data['group']
                if 'deprecated' in json_data:
                    function['group_deprecated'] = json_data['deprecated']

                function_map[function['name']] = function

    # Reorder to match original order: purely intended to keep the PR review sane
    function_groups_ordered = []

    if len(function_groups) != len(ORIGINAL_FUNCTION_GROUP_ORDER):
        print(
            "The list used to match the original order of function groups in the original the duckdb.h file does not match the new one. Did you add a new function group? please also add it to ORIGINAL_FUNCTION_GROUP_ORDER for now."
        )

    for order_group in ORIGINAL_FUNCTION_GROUP_ORDER:
        curr_group = next(group for group in function_groups if group['group'] == order_group)
        function_groups.remove(curr_group)
        function_groups_ordered.append(curr_group)

    return (function_groups_ordered, function_map)


# Read extension API
def parse_ext_api_definitions(ext_api_definition):
    api_definitions = {}
    versions = []
    dev_versions = []
    for file in list(glob.glob(ext_api_definition)):
        with open(file, 'r') as f:
            try:
                obj = json.loads(f.read())
                api_definitions[obj['version']] = obj

                if Path(file).stem != obj['version']:
                    print(f"\nMismatch between filename and version in file for {file}")
                    exit(1)
                if obj['version'] == DEV_VERSION_TAG:
                    dev_versions.append(obj['version'])
                else:
                    versions.append(obj['version'])

            except json.decoder.JSONDecodeError as err:
                print(f"\nInvalid JSON found in {file}: {err}")
                exit(1)

    versions.sort(key=Version)
    dev_versions.sort()

    return [api_definitions[x] for x in (versions + dev_versions)]


def parse_exclusion_list(function_map):
    exclusion_set = set()
    with open(EXT_API_EXCLUSION_FILE, 'r') as f:
        try:
            data = json.loads(f.read())
        except json.decoder.JSONDecodeError as err:
            print(f"\nInvalid JSON found in {EXT_API_EXCLUSION_FILE}: {err}")
            exit(1)

        for group in data['exclusion_list']:
            for entry in group['entries']:
                if entry not in function_map:
                    print(f"\nInvalid item found in exclusion list: {entry}. This entry does not occur in the API!")
                    exit(1)
                exclusion_set.add(entry)
    return exclusion_set


# Creates the comment that accompanies describing a C api function
def create_function_comment(function_obj):
    result = ''

    function_name = function_obj['name']
    # Construct comment
    if 'comment' in function_obj:
        comment = function_obj['comment']
        result += '/*!\n'
        result += comment['description']
        # result += '\n\n'
        if 'params' in function_obj:
            for param in function_obj['params']:
                param_name = param['name']
                if not 'param_comments' in comment:
                    if not ALLOW_UNCOMMENTED_PARAMS:
                        print(comment)
                        print(f'\nMissing param comments for function {function_name}')
                        exit(1)
                    continue
                if param['name'] in comment['param_comments']:
                    param_comment = comment['param_comments'][param['name']]
                    result += f'* @param {param_name} {param_comment}\n'
                elif not ALLOW_UNCOMMENTED_PARAMS:
                    print(f'\nUncommented parameter found: {param_name} of function {function_name}')
                    exit(1)
        if 'return_value' in comment:
            comment_return_value = comment['return_value']
            result += f'* @return {comment_return_value}\n'
        result += '*/\n'
    return result


# Creates the function declaration for the regular C header file
def create_function_declaration(function_obj):
    result = ''
    function_name = function_obj['name']
    function_return_type = function_obj['return_type']

    # Construct function declaration
    result += f'DUCKDB_API {function_return_type}'
    if result[-1] != '*':
        result += ' '
    result += f'{function_name}('

    if 'params' in function_obj:
        if len(function_obj['params']) > 0:
            for param in function_obj['params']:
                param_type = param['type']
                param_name = param['name']
                result += f'{param_type}'
                if result[-1] != '*':
                    result += ' '
                result += f'{param_name}, '
            result = result[:-2]  # Trailing comma
    result += ');\n'

    return result


# Creates the function declaration for extension api struct
def create_struct_member(function_obj):
    result = ''

    function_name = function_obj['name']
    function_return_type = function_obj['return_type']
    result += f'    {function_return_type} (*{function_name})('
    if 'params' in function_obj:
        if len(function_obj['params']) > 0:
            for param in function_obj['params']:
                param_type = param['type']
                param_name = param['name']
                result += f'{param_type} {param_name},'
            result = result[:-1]  # Trailing comma
    result += ');'

    return result


# Creates the function declaration for extension api struct
def create_function_typedef(function_obj):
    function_name = function_obj['name']
    return f'#define {function_name} {DUCKDB_EXT_API_VAR_NAME}.{function_name}\n'


def to_camel_case(snake_str):
    return " ".join(x.capitalize() for x in snake_str.lower().split("_"))


def parse_semver(version):
    if version[0] != 'v':
        print(f"\nVersion string {version} does not start with a v")
        exit(1)

    versions = version[1:].split(".")

    if len(versions) != 3:
        print(f"\nVersion string {version} is invalid, only vx.y.z is supported")
        exit(1)

    return int(versions[0]), int(versions[1]), int(versions[2])


def create_version_defines(version):
    major, minor, patch = parse_semver(version)

    version_string = f"v{major}.{minor}.{patch}"

    result = ""
    result += f"#define DUCKDB_EXTENSION_API_VERSION_MAJOR {major}\n"
    result += f"#define DUCKDB_EXTENSION_API_VERSION_MINOR {minor}\n"
    result += f"#define DUCKDB_EXTENSION_API_VERSION_PATCH {patch}\n"
    result += f"#define DUCKDB_EXTENSION_API_VERSION_STRING \"{version_string}\"\n"

    return result


# Create duckdb.h
def create_duckdb_h(ext_api_version, function_groups):
    function_declarations_finished = ''

    for curr_group in function_groups:
        function_declarations_finished += f'''//===--------------------------------------------------------------------===//
// {to_camel_case(curr_group['group'])}
//===--------------------------------------------------------------------===//\n\n'''

        if 'description' in curr_group:
            function_declarations_finished += curr_group['description'] + '\n'

        if 'deprecated' in curr_group and curr_group['deprecated']:
            function_declarations_finished += f'#ifndef DUCKDB_API_NO_DEPRECATED\n'

        for function in curr_group['entries']:
            if 'deprecated' in function and function['deprecated']:
                function_declarations_finished += '#ifndef DUCKDB_API_NO_DEPRECATED\n'

            function_declarations_finished += create_function_comment(function)
            function_declarations_finished += create_function_declaration(function)

            if 'deprecated' in function and function['deprecated']:
                function_declarations_finished += '#endif\n'

            function_declarations_finished += '\n'

        if 'deprecated' in curr_group and curr_group['deprecated']:
            function_declarations_finished += '#endif\n'

    header_template = fetch_header_template_main()
    duckdb_h = DUCKDB_H_HEADER + header_template.replace(BASE_HEADER_CONTENT_MARK, function_declarations_finished)
    with open(DUCKDB_HEADER_OUT_FILE, 'w+') as f:
        f.write(duckdb_h)


def write_struct_member_definitions(function_map, version_entries, initialize=False):
    result = ""
    if initialize:
        for function_name in version_entries:
            function_lookup = function_map[function_name]
            function_lookup_name = function_lookup['name']
            result += f'        result.{function_lookup_name} = {function_lookup_name};\n'
    elif len(version_entries) > 0:
        count = len(version_entries)
        first_function = version_entries[0]
        result += f'        memset(&result.{first_function}, 0, sizeof(result.{first_function}) * {count});\n'

    return result


def create_struct_version_defines(api_definition):
    result = "//! These defines control which version of the API is available\n"

    for i in range(1, len(api_definition) + 1):
        current_version = (api_definition)[-i]['version']
        if i < len(api_definition):
            prev_version = api_definition[-(i + 1)]['version']
        else:
            prev_version = None

        print(f"current: {current_version} prev: {prev_version}")

        if prev_version:
            prev_major, prev_minor, prev_patch = parse_semver(prev_version)
            if current_version == DEV_VERSION_TAG:
                result += "#ifdef  DUCKDB_EXTENSION_API_VERSION_DEV\n"
                result += f"#define  DUCKDB_EXTENSION_API_VERSION_{prev_major}_{prev_minor}_{prev_patch}\n"
                result += "#endif\n"
            else:
                major, minor, patch = parse_semver(current_version)
                result += f"#ifdef  DUCKDB_EXTENSION_API_VERSION_{major}_{minor}_{patch}\n"
                result += f"#define  DUCKDB_EXTENSION_API_VERSION_{prev_major}_{prev_minor}_{prev_patch}\n"
                result += "#endif\n"
        result += "\n"

    first_version = api_definition[0]['version']
    first_major, first_minor, first_patch = parse_semver(first_version)
    result += f"// No version was explicitly set, we assume latest\n"
    result += f"#ifndef  DUCKDB_EXTENSION_API_VERSION_{first_major}_{first_minor}_{first_patch}\n"
    result += f"#define  DUCKDB_EXTENSION_API_VERSION_LATEST\n"
    result += f"#endif\n"

    result += "\n"

    return result


def create_extension_api_struct(
    function_groups,
    function_map,
    api_definition,
    exclusion_set,
    with_create_method=False,
    add_version_defines=False,
    create_method_name='',
    validate_exclusion_list=True,
):
    functions_in_struct = set()

    # Generate the struct
    extension_struct_finished = COMMENT_HEADER("Function pointer struct")
    extension_struct_finished += 'typedef struct {\n'
    for api_version_entry in api_definition:
        version = api_version_entry['version']
        if version == DEV_VERSION_TAG:
            if add_version_defines:
                extension_struct_finished += f"#ifdef  DUCKDB_EXTENSION_API_VERSION_DEV // {version}\n"
            else:
                extension_struct_finished += f"// {version}\n"
            extension_struct_finished += f'    // WARNING! the functions below are not (yet) stable \n\n'
        else:
            if add_version_defines:
                major, minor, patch = parse_semver(version)
                version_define = f" DUCKDB_EXTENSION_API_VERSION_{major}_{minor}_{patch}"
                extension_struct_finished += f"#if  DUCKDB_EXTENSION_API_VERSION_MINOR >= {minor} &&  DUCKDB_EXTENSION_API_VERSION_PATCH >= {patch} // {version}\n"
            else:
                extension_struct_finished += f"// {version}\n"
        for function_name in api_version_entry['entries']:
            function_lookup = function_map[function_name]
            functions_in_struct.add(function_lookup['name'])
            extension_struct_finished += create_struct_member(function_lookup)
            extension_struct_finished += '\n'
        if add_version_defines:
            extension_struct_finished += "#endif\n\n"
    extension_struct_finished += '} ' + f'{DUCKDB_EXT_API_STRUCT_TYPENAME};\n\n'

    if validate_exclusion_list:
        # Check for missing entries
        missing_entries = []
        for group in function_groups:
            for function in group['entries']:
                if function['name'] not in functions_in_struct and function['name'] not in exclusion_set:
                    missing_entries.append(function['name'])
        if missing_entries:
            print(
                "\nExclusion list validation failed! This means a C API function has been defined but not added to the API struct nor the exclusion list"
            )
            print(f" * Missing functions: {missing_entries}")
            exit(1)
        # Check for entries both in the API definition and the exclusion list
        double_entries = []
        for api_version_entry in api_definition:
            for function_name in api_version_entry['entries']:
                if function_name in exclusion_set:
                    double_entries.append(function_name)
        if double_entries:
            print(
                "\nExclusion list is invalid, there are entries in the extension api that are also in the exclusion list!"
            )
            print(f" * Missing functions: {double_entries}")
            exit(1)

    if with_create_method:
        extension_struct_finished += COMMENT_HEADER("Struct Create Method")
        extension_struct_finished += f"inline {DUCKDB_EXT_API_STRUCT_TYPENAME} {create_method_name}() {{\n"
        extension_struct_finished += f"    {DUCKDB_EXT_API_STRUCT_TYPENAME} result;\n"
        for api_version_entry in api_definition:

            if len(api_version_entry['entries']) == 0:
                continue

            extension_struct_finished += write_struct_member_definitions(
                function_map, api_version_entry['entries'], initialize=True
            )

        extension_struct_finished += "    return result;\n"
        extension_struct_finished += "}\n\n"

    return extension_struct_finished


# Create duckdb_extension_api.h
def create_duckdb_ext_h(
    file, ext_api_version, function_groups, api_struct_definition, struct_function_set, exclusion_set
):
    # Generate the typedefs
    typedefs = ""
    for api_version_entry in api_struct_definition:
        version = api_version_entry['version']
        typedefs += f"// Version {version}\n"

        for group in function_groups:
            functions_to_add = []
            for function in group['entries']:
                if function['name'] not in api_version_entry['entries']:
                    continue
                functions_to_add.append(function)

            if functions_to_add:
                group_name = group['group']
                # typedefs += f'//! {group_name}\n'
                for fun_to_add in functions_to_add:
                    typedefs += create_function_typedef(fun_to_add)

                typedefs += '\n'

    # Create the versioning defines
    major, minor, patch = parse_semver(ext_api_version)
    versioning_defines = f"""//! Set version to latest if no explicit version is defined
#if !defined(DUCKDB_EXTENSION_API_VERSION_MAJOR) && !defined(DUCKDB_EXTENSION_API_VERSION_MINOR) && !defined(DUCKDB_EXTENSION_API_VERSION_PATCH)
#define DUCKDB_EXTENSION_API_VERSION_MAJOR {major}
#define DUCKDB_EXTENSION_API_VERSION_MINOR {minor}
#define DUCKDB_EXTENSION_API_VERSION_PATCH {patch}
#elif !(defined(DUCKDB_EXTENSION_API_VERSION_MAJOR) && defined(DUCKDB_EXTENSION_API_VERSION_MINOR) && defined(DUCKDB_EXTENSION_API_VERSION_PATCH))
#error "either all or none of the  DUCKDB_EXTENSION_API_VERSION_ defines should be defined"
#endif

//! Set the DUCKDB_EXTENSION_API_VERSION_STRING which is passed to DuckDB on extension load
#if DUCKDB_EXTENSION_API_VERSION_DEV
#define DUCKDB_EXTENSION_API_VERSION_STRING "dev"
#else
#define DUCKDB_EXTENSION_API_VERSION_STRING DUCKDB_EXTENSION_SEMVER_STRING(DUCKDB_EXTENSION_API_VERSION_MAJOR, DUCKDB_EXTENSION_API_VERSION_MINOR, DUCKDB_EXTENSION_API_VERSION_PATCH)
#endif

#if DUCKDB_EXTENSION_API_VERSION_MAJOR != {major}
#error "This version of the extension API header only supports API VERSION v{major}.x.x"
#endif
"""

    # Begin constructing the header file
    duckdb_ext_h = ""
    duckdb_ext_h += DUCKDB_EXT_H_HEADER
    duckdb_ext_h += fetch_header_template_ext()
    duckdb_ext_h += COMMENT_HEADER("Util Macros")
    duckdb_ext_h += HELPER_MACROS

    duckdb_ext_h += COMMENT_HEADER("Versioning")
    duckdb_ext_h += versioning_defines
    duckdb_ext_h += "\n"
    duckdb_ext_h += create_extension_api_struct(
        function_groups, function_map, api_struct_definition, exclusion_set, add_version_defines=True
    )
    duckdb_ext_h += "\n\n"
    duckdb_ext_h += COMMENT_HEADER("Typedefs mapping functions to struct entries")
    duckdb_ext_h += typedefs
    duckdb_ext_h += "\n"

    # Add The struct global macros
    duckdb_ext_h += COMMENT_HEADER("Struct Global Macros")
    duckdb_ext_h += f"""// This goes in the c/c++ file containing the entrypoint (handle
#define DUCKDB_EXTENSION_GLOBAL {DUCKDB_EXT_API_STRUCT_TYPENAME} {DUCKDB_EXT_API_VAR_NAME} = {{0}};
// Initializes the C Extension API: First thing to call in the extension entrypoint
#define DUCKDB_EXTENSION_API_INIT(info, access, minimum_api_version) {DUCKDB_EXT_API_STRUCT_TYPENAME} * res = ({DUCKDB_EXT_API_STRUCT_TYPENAME} *)access->get_api(info, minimum_api_version); if (!res) {{return;}}; {DUCKDB_EXT_API_VAR_NAME} = *res;
"""
    duckdb_ext_h += f"""
// Place in global scope of any C/C++ file that needs to access the extension API
#define DUCKDB_EXTENSION_EXTERN extern {DUCKDB_EXT_API_STRUCT_TYPENAME} {DUCKDB_EXT_API_VAR_NAME};

"""
    # Add the entrypoint macros
    duckdb_ext_h += COMMENT_HEADER("Entrypoint Macros")
    duckdb_ext_h += """
// Note: the DUCKDB_EXTENSION_ENTRYPOINT macro requires DUCKDB_EXTENSION_NAME to be set.  

#ifdef DUCKDB_EXTENSION_NAME

// Main entrypoint: opens (and closes) a connection automatically for the extension to register its functionality through 
#define DUCKDB_EXTENSION_ENTRYPOINT\
	DUCKDB_EXTENSION_GLOBAL static void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)(duckdb_connection connection, duckdb_extension_info info, duckdb_extension_access *access);\
	    DUCKDB_EXTENSION_EXTERN_C_GUARD_OPEN\
	    DUCKDB_EXTENSION_API void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api)(\
	    duckdb_extension_info info, duckdb_extension_access *access) {\
		DUCKDB_EXTENSION_API_INIT(info, access, DUCKDB_EXTENSION_API_VERSION_STRING);\
		duckdb_database *db = access->get_database(info);\
		duckdb_connection conn;\
		if (duckdb_connect(*db, &conn) == DuckDBError) {\
			access->set_error(info, "Failed to open connection to database");\
			return;\
		}\
		DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)(conn, info, access);\
		duckdb_disconnect(&conn);\
	}\
	DUCKDB_EXTENSION_EXTERN_C_GUARD_CLOSE static void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)

// Custom entrypoint: just forwards the info and access
#define DUCKDB_EXTENSION_ENTRYPOINT_CUSTOM\
	DUCKDB_EXTENSION_GLOBAL static void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)(\
	    duckdb_extension_info info, duckdb_extension_access *access);\
	    DUCKDB_EXTENSION_EXTERN_C_GUARD_OPEN\
	    DUCKDB_EXTENSION_API void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api)(\
	    duckdb_extension_info info, duckdb_extension_access *access) {\
		DUCKDB_EXTENSION_API_INIT(info, access, DUCKDB_EXTENSION_API_VERSION_STRING);\
		DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)(info, access);\
	}\
	DUCKDB_EXTENSION_EXTERN_C_GUARD_CLOSE static void DUCKDB_EXTENSION_GLUE(DUCKDB_EXTENSION_NAME,_init_c_api_internal)
#endif
    """

    with open(file, 'w+') as f:
        f.write(duckdb_ext_h)


# Create duckdb_extension_internal.hpp
def create_duckdb_ext_internal_h(ext_api_version, function_groups, function_map, ext_api_definitions, exclusion_set):
    duckdb_ext_h = fetch_header_template_ext()
    duckdb_ext_h += create_extension_api_struct(
        function_groups,
        function_map,
        ext_api_definitions,
        exclusion_set,
        with_create_method=True,
        create_method_name='CreateAPIv0',
    )
    duckdb_ext_h += create_version_defines(ext_api_version)

    with open(DUCKDB_HEADER_EXT_INTERNAL_OUT_FILE, 'w+') as f:
        f.write(duckdb_ext_h)


def get_extension_api_version(ext_api_definitions):
    versions = []

    for version_entry in ext_api_definitions:
        versions.append(version_entry['version'])

    if versions[-1] == DEV_VERSION_TAG:
        return versions[-2]
    else:
        return versions[-1]


def create_struct_function_set(api_definitions):
    result = set()
    for api in api_definitions:
        for entry in api['entries']:
            result.add(entry)
    return result


if __name__ == "__main__":
    # parse the api definition (which fields make it into the struct)
    ext_api_definitions = parse_ext_api_definitions(EXT_API_DEFINITION_PATTERN)

    # extract a set of the function names and the latest version of the api definition
    ext_api_set = create_struct_function_set(ext_api_definitions)
    ext_api_version = get_extension_api_version(ext_api_definitions)

    function_groups, function_map = parse_capi_function_definitions()
    function_map_size = len(function_map)

    api_struct_function_count = sum([len(y['entries']) for y in ext_api_definitions])
    ext_api_exclusion_set = parse_exclusion_list(function_map)
    ext_api_exclusion_set_size = len(ext_api_exclusion_set)

    print("Information")
    print(f" * Current Extension C API Version: {ext_api_version}")
    print(f" * Total functions: {function_map_size}")
    print(f" * Functions in C API struct: {api_struct_function_count}")
    print(f" * Functions in C API but excluded from struct: {ext_api_exclusion_set_size}")

    print()

    print("Generating headers")
    print(f" * {DUCKDB_HEADER_OUT_FILE}")
    create_duckdb_h(ext_api_version, function_groups)
    print(f" * {DUCKDB_HEADER_EXT_OUT_FILE}")
    create_duckdb_ext_h(
        DUCKDB_HEADER_EXT_OUT_FILE,
        ext_api_version,
        function_groups,
        ext_api_definitions,
        ext_api_set,
        ext_api_exclusion_set,
    )
    print(f" * {DUCKDB_HEADER_EXT_INTERNAL_OUT_FILE}")
    create_duckdb_ext_internal_h(
        ext_api_version, function_groups, function_map, ext_api_definitions, ext_api_exclusion_set
    )

    print()

    os.system(f"python3 scripts/format.py {DUCKDB_HEADER_OUT_FILE} --fix --noconfirm")
    os.system(f"python3 scripts/format.py {DUCKDB_HEADER_EXT_OUT_FILE} --fix --noconfirm")
    os.system(f"python3 scripts/format.py {DUCKDB_HEADER_EXT_INTERNAL_OUT_FILE} --fix --noconfirm")

    print()
    print("C API headers generated successfully!")
