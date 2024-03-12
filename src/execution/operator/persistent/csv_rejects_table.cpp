#include "duckdb/main/appender.hpp"
#include "duckdb/parser/parsed_data/create_table_info.hpp"
#include "duckdb/function/table/read_csv.hpp"
#include "duckdb/execution/operator/persistent/csv_rejects_table.hpp"
#include "duckdb/catalog/catalog_entry/table_catalog_entry.hpp"
#include "duckdb/parser/parsed_data/create_type_info.hpp"

namespace duckdb {

TableCatalogEntry &CSVRejectsTable::GetErrorsTable(ClientContext &context) {
	auto &temp_catalog = Catalog::GetCatalog(context, TEMP_CATALOG);
	auto &table_entry = temp_catalog.GetEntry<TableCatalogEntry>(context, TEMP_CATALOG, DEFAULT_SCHEMA, errors_table);
	return table_entry;
}

TableCatalogEntry &CSVRejectsTable::GetScansTable(ClientContext &context) {
	auto &temp_catalog = Catalog::GetCatalog(context, TEMP_CATALOG);
	auto &table_entry = temp_catalog.GetEntry<TableCatalogEntry>(context, TEMP_CATALOG, DEFAULT_SCHEMA, scan_table);
	return table_entry;
}

shared_ptr<CSVRejectsTable> CSVRejectsTable::GetOrCreate(ClientContext &context, const string &rejects_scan,
                                                         const string &rejects_error) {
	auto key =
	    "CSV_REJECTS_TABLE_CACHE_ENTRY_" + StringUtil::Upper(rejects_scan) + "_" + StringUtil::Upper(rejects_error);
	auto &cache = ObjectCache::GetObjectCache(context);
	return cache.GetOrCreate<CSVRejectsTable>(key, rejects_scan, rejects_error);
}

void CSVRejectsTable::InitializeTable(ClientContext &context, const ReadCSVData &data) {
	// (Re)Create the temporary rejects table
	auto &catalog = Catalog::GetCatalog(context, TEMP_CATALOG);

	// Create CSV_ERROR_TYPE ENUM
	string enum_name = "CSV_ERROR_TYPE";
	Vector order_errors(LogicalType::VARCHAR, 6);
	order_errors.SetValue(0, "CAST");
	order_errors.SetValue(1, "MISSING COLUMNS");
	order_errors.SetValue(2, "TOO MANY COLUMNS");
	order_errors.SetValue(3, "UNQUOTED VALUE");
	order_errors.SetValue(4, "LINE SIZE OVER MAXIMUM");
	order_errors.SetValue(5, "INVALID UNICODE");
	LogicalType enum_type = LogicalType::ENUM(enum_name, order_errors, 6);
	auto type_info = make_uniq<CreateTypeInfo>(enum_name, enum_type);
	type_info->temporary = true;
	type_info->on_conflict = OnCreateConflict::IGNORE_ON_CONFLICT;
	catalog.CreateType(context, *type_info);

	// Create Rejects Scans Table
	{
		auto info = make_uniq<CreateTableInfo>(TEMP_CATALOG, DEFAULT_SCHEMA, scan_table);
		info->temporary = true;
		info->on_conflict = OnCreateConflict::ERROR_ON_CONFLICT;
		// 0. Scan ID
		info->columns.AddColumn(ColumnDefinition("scan_id", LogicalType::UBIGINT));
		// 1. File ID (within the scan)
		info->columns.AddColumn(ColumnDefinition("file_id", LogicalType::UBIGINT));
		// 2. File Path
		info->columns.AddColumn(ColumnDefinition("file_path", LogicalType::VARCHAR));
		// 3. Delimiter
		info->columns.AddColumn(ColumnDefinition("delimiter", LogicalType::VARCHAR));
		// 4. Quote
		info->columns.AddColumn(ColumnDefinition("quote", LogicalType::VARCHAR));
		// 5. Escape
		info->columns.AddColumn(ColumnDefinition("escape", LogicalType::VARCHAR));
		// 6. NewLine Delimiter
		info->columns.AddColumn(ColumnDefinition("newline_delimiter", LogicalType::VARCHAR));
		// 7. Skip Rows
		info->columns.AddColumn(ColumnDefinition("skip_rows", LogicalType::UINTEGER));
		// 8. Has Header
		info->columns.AddColumn(ColumnDefinition("has_header", LogicalType::BOOLEAN));
		// 9. List<Struct<Column-Name:Types>>
		info->columns.AddColumn(ColumnDefinition("columns", LogicalType::VARCHAR));
		// 10. Date Format
		info->columns.AddColumn(ColumnDefinition("date_format", LogicalType::VARCHAR));
		// 11. Timestamp Format
		info->columns.AddColumn(ColumnDefinition("timestamp_format", LogicalType::VARCHAR));
		// 12. CSV read function with all the options used
		info->columns.AddColumn(ColumnDefinition("user_arguments", LogicalType::VARCHAR));
		catalog.CreateTable(context, std::move(info));
	}
	{
		// Create Rejects Error Table
		auto info = make_uniq<CreateTableInfo>(TEMP_CATALOG, DEFAULT_SCHEMA, errors_table);
		info->temporary = true;
		info->on_conflict = OnCreateConflict::ERROR_ON_CONFLICT;
		// 0. Scan ID
		info->columns.AddColumn(ColumnDefinition("scan_id", LogicalType::UBIGINT));
		// 1. File ID (within the scan)
		info->columns.AddColumn(ColumnDefinition("file_id", LogicalType::UBIGINT));
		// 2. Row Line
		info->columns.AddColumn(ColumnDefinition("line", LogicalType::UBIGINT));
		// 3. Byte Position where error occurred
		info->columns.AddColumn(ColumnDefinition("byte_position", LogicalType::UBIGINT));
		// 4. Column Index (If Applicable)
		info->columns.AddColumn(ColumnDefinition("column_idx", LogicalType::UBIGINT));
		// 5. Column Name (If Applicable)
		info->columns.AddColumn(ColumnDefinition("column_name", LogicalType::VARCHAR));
		// 6. Error Type
		info->columns.AddColumn(ColumnDefinition("error_type", enum_type));
		// 7. Original CSV Line
		info->columns.AddColumn(ColumnDefinition("csv_line", LogicalType::VARCHAR));
		// 8. Full Error Message
		info->columns.AddColumn(ColumnDefinition("error_message", LogicalType::VARCHAR));
		catalog.CreateTable(context, std::move(info));
	}

	count = 0;
}

} // namespace duckdb
