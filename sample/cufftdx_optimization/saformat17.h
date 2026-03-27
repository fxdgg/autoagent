/* 
saformat.h: a simple yet powerful implementation of fmt library
*/

#pragma once

#ifndef _MSC_VER
#include <unistd.h>
#endif

#include "saformat17_internal.h"

namespace safmt
{
    template <typename... Args>
    inline std::string format(const std::string& fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }

    template <typename... Args>
    inline std::string format(const char* fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }

    template <typename... Args>
    inline int format_to(char* buf, int size, const std::string& fmt, Args&&... args)
    {
        // create format context, with resizable = false
        detail::c17::fmt_context context(buf, size, false);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // return actual written size
        return context.size();
    }

    template <typename... Args>
    inline int format_to(char* buf, int size, const char* fmt, Args&&... args)
    {
        // create format context, with resizable = false
        detail::c17::fmt_context context(buf, size, false);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // return actual written size
        return context.size();
    }

    template <typename... Args>
    inline void format_to(detail::c17::fmt_context& context, const std::string& fmt, Args&&... args)
    {
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    inline void format_to(detail::c17::fmt_context& context, const char* fmt, Args&&... args)
    {
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    inline void print(const std::string& fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // call std::cout
        std::cout << context.data();
    }

    template <typename... Args>
    inline void println(const std::string& fmt, Args&&... args)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        // add \n to the buffer
        context.append_endl();
        context.eof();
        // call std::cout
        std::cout << context.data();
    }

    template <typename... Args>
    inline void print_err(const std::string& fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // call std::cerr
        std::cerr << context.data();
    }

    template <typename... Args>
    inline void println_err(const std::string& fmt, Args&&... args)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        // add \n to the buffer
        context.append_endl();
        context.eof();
        // call std::cerr
        std::cerr << context.data();
    }

    template <typename... Args>
    inline void print(const char* fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // call std::cout
        std::cout << context.data();
    }

    template <typename... Args>
    inline void println(const char* fmt, Args&&... args)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        // add \n to the buffer
        context.append_endl();
        context.eof();
        // call std::cout
        std::cout << context.data();
    }

    template <typename... Args>
    inline void print_err(const char* fmt, Args&&... args)
    {
        // initial buffer
        char buf[detail::c17::initbufsize];
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        context.eof();
        // call std::cerr
        std::cerr << context.data();
    }

    template <typename... Args>
    inline void println_err(const char* fmt, Args&&... args)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::format_to(context, fmt, std::forward<Args>(args)...);
        // add \n to the buffer
        context.append_endl();
        context.eof();
        // call std::cerr
        std::cerr << context.data();
    }

    template <typename T>
    inline std::string join(const T& container, const std::string& sep)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::to_string_join(context, false, nullptr, container, sep.c_str(), static_cast<int>(sep.size()));
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }

    template <typename T>
    inline std::string join(const T& container, const char* sep)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::to_string_join(context, false, nullptr, container, sep, static_cast<int>(std::strlen(sep)));
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }

    template <typename T, typename Formatter>
    inline std::string join(const T& container, const std::string& sep, Formatter formatter)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::to_string_join_formatter(context, container, sep.c_str(), static_cast<int>(sep.size()), formatter);
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }

    template <typename T, typename Formatter>
    inline std::string join(const T& container, const char* sep, Formatter formatter)
    {
        // initial buffer size
        char buf[detail::c17::initbufsize]; 
        // create format context
        detail::c17::fmt_context context(buf, detail::c17::initbufsize, true);
        // call implementation
        detail::c17::to_string_join_formatter(context, container, sep, std::strlen(sep), formatter);
        context.eof();
        // generate the string
        return std::string(context.data(), context.size());
    }
}