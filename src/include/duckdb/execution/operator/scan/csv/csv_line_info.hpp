//===----------------------------------------------------------------------===//
//                         DuckDB
//
// duckdb/execution/operator/scan/csv/csv_line_info.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

namespace duckdb {
struct LineInfo {
public:
	explicit LineInfo(mutex &main_mutex_p, vector<unordered_map<idx_t, idx_t>> &batch_to_tuple_end_p,
	                  string mismatch_error)
	    : main_mutex(main_mutex_p), batch_to_tuple_end(batch_to_tuple_end_p),
	      sniffer_mismatch_error(std::move(mismatch_error)) {};
	bool CanItGetLine(idx_t file_idx, idx_t batch_idx);

	//! Return the 1-indexed line number
	idx_t GetLine(idx_t batch_idx, idx_t line_error = 0, idx_t file_idx = 0, idx_t cur_start = 0, bool verify = true,
	              bool stop_at_first = true);
	//! In case an error happened we have to increment the lines read of that batch
	void Increment(idx_t file_idx, idx_t batch_idx);
	//! Verify if the CSV File was read correctly from [0,batch_idx] batches.
	void Verify(idx_t file_idx, idx_t batch_idx, idx_t cur_first_pos);
	//! Lines read per batch, <file_index, <batch_index, count>>
	vector<unordered_map<idx_t, idx_t>> lines_read;
	//! Lines read per batch, <file_index, <batch_index, count>>
	vector<unordered_map<idx_t, idx_t>> lines_errored;
	//! Set of batches that have been initialized but are not yet finished.
	vector<set<idx_t>> current_batches;
	//! Pointer to CSV Reader Mutex
	mutex &main_mutex;
	//! Pointer Batch to Tuple End
	vector<unordered_map<idx_t, idx_t>> &batch_to_tuple_end;
	//! If we already threw an exception on a previous thread.
	bool done = false;
	idx_t first_line = 0;
	string sniffer_mismatch_error;
};

} // namespace duckdb
