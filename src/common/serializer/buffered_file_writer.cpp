#include "common/serializer/buffered_file_writer.hpp"
#include "common/exception.hpp"

#include <cstring>

using namespace duckdb;
using namespace std;

BufferedFileWriter::BufferedFileWriter(FileSystem &fs, const char *path, bool append)
    : fs(fs), data(unique_ptr<data_t[]>(new data_t[FILE_BUFFER_SIZE])), offset(0) {
	uint8_t flags = FileFlags::WRITE | FileFlags::CREATE;
	if (append) {
		flags |= FileFlags::APPEND;
	}
	handle = fs.OpenFile(path, flags, FileLockType::WRITE_LOCK);
}

void BufferedFileWriter::WriteData(const_data_ptr_t buffer, uint64_t write_size) {
	// first copy anything we can from the buffer
	const_data_ptr_t end_ptr = buffer + write_size;
	while (buffer < end_ptr) {
		index_t to_write = std::min((index_t)(end_ptr - buffer), FILE_BUFFER_SIZE - offset);
		assert(to_write > 0);
		memcpy(data.get() + offset, buffer, to_write);
		offset += to_write;
		buffer += to_write;
		if (offset == FILE_BUFFER_SIZE) {
			Flush();
		}
	}
}

void BufferedFileWriter::Flush() {
	if (offset == 0) {
		return;
	}
	fs.Write(*handle, data.get(), offset);
	offset = 0;
}

void BufferedFileWriter::Sync() {
	Flush();
	handle->Sync();
}
