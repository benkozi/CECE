/**
 * @file cece_log_setup.hpp
 * @brief Optional run-log file support for the standalone driver.
 *
 * Allows the control file to specify a log filename so users no longer need to
 * redirect stdout manually (e.g. `> cece.log`). Output is *tee'd*: it is written
 * both to the original console/stdout and to the log file, so live progress is
 * still visible while a persistent copy is captured.
 */

#ifndef CECE_LOG_SETUP_HPP
#define CECE_LOG_SETUP_HPP

#include <fstream>
#include <ostream>
#include <streambuf>

namespace cece {

/**
 * @class TeeStreambuf
 * @brief A stream buffer that forwards all output to two underlying buffers.
 */
class TeeStreambuf : public std::streambuf {
   public:
    TeeStreambuf(std::streambuf* first, std::streambuf* second) : first_(first), second_(second) {}

   protected:
    int overflow(int ch) override {
        if (ch == traits_type::eof()) {
            return traits_type::not_eof(ch);
        }
        const int r1 = first_ ? first_->sputc(static_cast<char>(ch)) : ch;
        const int r2 = second_ ? second_->sputc(static_cast<char>(ch)) : ch;
        return (r1 == traits_type::eof() || r2 == traits_type::eof()) ? traits_type::eof() : ch;
    }

    int sync() override {
        const int r1 = first_ ? first_->pubsync() : 0;
        const int r2 = second_ ? second_->pubsync() : 0;
        return (r1 == 0 && r2 == 0) ? 0 : -1;
    }

   private:
    std::streambuf* first_;
    std::streambuf* second_;
};

}  // namespace cece

#endif  // CECE_LOG_SETUP_HPP
