#pragma once

#include <string>
#include <string_view>
#include <cstring>

#include <vector>
#include <array>
#include <set>
#include <map>
#include <unordered_set>
#include <unordered_map>

#include <type_traits>

#include <stdexcept>

#include <algorithm>

#include <iostream>
#include <sstream>

#include <charconv>

#ifndef _MSC_VER
#include <cxxabi.h>
#endif

namespace safmt
{
    namespace detail
    {
        namespace c17
        {
            static constexpr const int initbufsize = 128;

            // ----------------------------------------- report format errors ----------------------------------------------
            // report general error
            inline void format_error(const char* errmsg);

            // report parameter error
            inline void format_param_error_internal(const char* errmsg, int paramidx, const char* name);
            inline void format_param_error_internal(const char* errmsg, int errcode, int paramidx, const char* name);

            template <typename T>
            inline void format_param_error(const char* errmsg, int paramidx)
            {
                format_param_error_internal(errmsg, paramidx, typeid(T).name());
            }
            template <typename T>
            inline void format_param_error(const char* errmsg, int errcode, int paramidx)
            {
                format_param_error_internal(errmsg, errcode, paramidx, typeid(T).name());
            }

            // report format string parse error
            void format_parse_error(const std::string& fmt, const char* errmsg, int idx);

            // ----------------------------------------------- format context -------------------------------------------------
            class fmt_context
            {
            private:
                // current buffer
                char* buf; 
                // whether or not it is initial buffer
                bool init; 
                // current filled size of the buffer
                int cursize; 
                // maximum size of the buffer
                int maxsize;
                // whether or not the buffer is resizable
                bool resizable;

                // reallocate the buffer
                void reallocate()
                {
                    // allocate new buffer
                    char* newbuf = new char[maxsize];
                    // copy original content to new buffer
                    std::memcpy(newbuf, buf, cursize);
                    // delete original buffer and swap buffers
                    if (!init)
                        delete[] buf;
                    buf = newbuf;
                    init = false;
                }

                // judge whether or not reallocation is needed
                bool resize(int thissize)
                {
                    int remain = maxsize - cursize - thissize;
                    // must reserve a place for '\0'
                    if (remain >= 1)
                        return true;
                    // if not resizable, return false
                    if (!resizable)
                        return false;
                    // unroll the loop once for better branch prediction
                    maxsize <<= 1;
                    remain = maxsize - cursize - thissize;
                    while (remain < 1)
                    {
                        maxsize <<= 1;
                        remain = maxsize - cursize - thissize;
                    }
                    // reallocate the buffer
                    reallocate();
                    return true;
                }

            public:
                fmt_context(char* buf, int maxsize, bool resizable) : buf(buf), init(true), cursize(0), maxsize(maxsize), resizable(resizable) {}

                ~fmt_context() 
                {
                    if (!init)
                        delete[] buf;
                }

                // null-terminate the buffer
                void eof() { buf[cursize] = '\0'; }

                // return the inner buffer (not null-terminated)
                const char* data() const { return buf; }

                // return the size of inner buffer
                int size() const { return cursize; }

                // append a char to the buffer
                void append_char(char ch)
                {
                    if (!resize(1))
                        return;
                    buf[cursize++] = ch;
                }

                // append a string with specified size to the buffer
                void append_str(const char* str, int thissize)
                {
                    if (!str)
                        return;
                    // if not having enough space, only copy a part of it
                    if (!resize(thissize))
                    {
                        int remain = maxsize - cursize - 1;
                        std::memcpy(buf + cursize, str, remain);
                        cursize += remain;
                        return;
                    }
                    // use memcpy to copy string
                    std::memcpy(buf + cursize, str, thissize);
                    cursize += thissize;
                }

                // append a string with unspecified size to the buffer
                void append_str(char* str)
                {
                    append_str(str, static_cast<int>(std::strlen(str)));
                }

                // append an arithmetic value to the buffer
                // paramidx: the position of parameter, used for error report
                template <typename T>
                void append_arith(const T& value, int paramidx = -1)
                {
                    // normal case: directly write to original buffer (reserve one space for '\0')
                    auto ret = std::to_chars(buf + cursize, buf + maxsize - 1, value);
                    // if the buffer is too small, then reallocate and reconvert
                    // again, unroll the loop once for better branch prediction
                    if (ret.ec == std::errc::value_too_large)
                    {
                        maxsize <<= 1;
                        reallocate();
                        ret = std::to_chars(buf + cursize, buf + maxsize - 1, value);
                    }
                    while (ret.ec == std::errc::value_too_large)
                    {
                        maxsize <<= 1;
                        reallocate();
                        ret = std::to_chars(buf + cursize, buf + maxsize - 1, value);
                    }
                    // if error occured, then report error
                    if (ret.ec != std::errc())
                        format_param_error<T>("failed to convert arithmetic value", static_cast<int>(ret.ec), paramidx);
                    // add cursize
                    cursize += static_cast<int>(ret.ptr - buf) - cursize;
                }

                // append an arithmetic value, with custom formatting method, to the buffer
                // paramidx: the position of parameter, used for error report
                template <typename T>
                void append_arith_fmt(const char* fmtspec, const T& value, int paramidx = -1)
                {
                    // use snprintf to print to buffer
                    int remainsize = maxsize - cursize;
                    int required = std::snprintf(buf + cursize, remainsize, fmtspec, value);
                    // if we don't have enough size, then resize the buffer and print again
                    if (required >= remainsize)
                    {
                        // if resizable = false, since snprintf always null-terminates the buffer, we directly return
                        if (!resizable)
                        {
                            cursize = maxsize - 1;
                            return;
                        }
                        // unroll the loop once for better branch prediction
                        maxsize <<= 1;
                        remainsize = maxsize - cursize;
                        while (required >= remainsize)
                        {
                            maxsize <<= 1;
                            remainsize = maxsize - cursize;
                        }
                        reallocate();
                        required = std::snprintf(buf + cursize, remainsize, fmtspec, value);
                    }
                    if (required < 0)
                        format_param_error<T>("internal snprintf failed", paramidx);
                    cursize += required;
                }

                // append a endl to the buffer
                void append_endl()
                {
                    if (!resize(1))
                        return;
                    buf[cursize++] = '\n';
                }
            };

            // ---------------------- custom type_traits to judge whether it is a specific STL type ---------------------------
            template<typename T> struct is_std_pair : std::false_type {};
            template<typename... Args> struct is_std_pair<std::pair<Args...>> : std::true_type {};

            template<typename T> struct is_std_array : std::false_type {};
            template<typename Args, std::size_t N> struct is_std_array<std::array<Args, N>> : std::true_type {};

            template<typename T> struct is_std_vector : std::false_type {};
            template<typename... Args> struct is_std_vector<std::vector<Args...>> : std::true_type {};

            template<typename T> struct is_std_set : std::false_type {};
            template<typename... Args> struct is_std_set<std::set<Args...>> : std::true_type {};

            template<typename T> struct is_std_map : std::false_type {};
            template<typename... Args> struct is_std_map<std::map<Args...>> : std::true_type {};

            template<typename T> struct is_std_unordered_set : std::false_type {};
            template<typename... Args> struct is_std_unordered_set<std::unordered_set<Args...>> : std::true_type {};

            template<typename T> struct is_std_unordered_map : std::false_type {};
            template<typename... Args> struct is_std_unordered_map<std::unordered_map<Args...>> : std::true_type {};

            /*
            ----------------------------------- step 2: convert complex types to std::string ----------------------------------- 
            to_string_join: format ranges only, seperated by sep
            to_string: format all supported types

            inner: if inner = true, then strings are wrapped with ""
            index: the index of the parameter, used for error report
            fmtspec: the format specifier that will pass to inner printf
            fmtter: custom formatter functions for inner type of the container
            */
            
            // custom to_string function puts here
            template <typename T>
            inline void to_string(fmt_context& context, const char* fmtspec, const T& value)
            {
                throw "unimplemented";
            }
            // custom to_string_join function puts here
            template <typename T>
            inline void to_string_join(fmt_context& context, const char* fmtspec, const T& value, const char* sep, int sepsize)
            {
                throw "unimplemented";
            }

            template <typename T>
            inline void to_string_join(fmt_context& context, bool inner, const char* fmtspec, const T& value, const char* sep, int sepsize);

            template <typename T>
            inline void to_string(fmt_context& context, bool inner, int index, const char* fmtspec, const T& value)
            {
                // arithmetic
                if constexpr (std::is_arithmetic_v<T>)
                {
                    if (fmtspec)
                    {
                        // simple check of whether or not %s is provided
                        if (!std::strcmp(fmtspec, "%s"))
                            format_param_error<T>("found %s, but not providing string, instead", index);
                        context.append_arith_fmt(fmtspec, value, index);
                    }
                    else 
                    {
                        // bool
                        if constexpr (std::is_same_v<T, bool>)
                        {
                            static constexpr const char* boolstr[] = {"false", "true"};
                            static constexpr const int boolsize[] = {5, 4};
                            context.append_str(boolstr[value], boolsize[value]);
                        }
                        // char
                        else if constexpr (std::is_same_v<T, char>)
                            context.append_char(value);
                        // general
                        else
                            context.append_arith(value, index);
                    }
                }
                // char*
                else if constexpr (std::is_same_v<std::remove_const_t<std::decay_t<T>>, char*> || std::is_same_v<std::remove_const_t<std::decay_t<T>>, const char*>)
                {
                    if (inner)
                        context.append_char('\"');
                    context.append_str(const_cast<char*>(value));
                    if (inner)
                        context.append_char('\"');
                }
                // other pointer
                else if constexpr (std::is_pointer_v<std::decay_t<T>>)
                    context.append_arith_fmt("%p", value);
                // std::string
                else if constexpr (std::is_same_v<T, std::string>)
                {
                    if (inner)
                        context.append_char('\"');
                    context.append_str(value.data(), static_cast<int>(value.size()));
                    if (inner)
                        context.append_char('\"');
                }
                // std::pair
                else if constexpr (is_std_pair<T>::value)
                {
                    context.append_char('{');
                    to_string_join(context, true, fmtspec, value, ", ", 2);
                    context.append_char('}');
                }
                // std::array / std::vector / std::set / std::unordered_set
                else if constexpr (is_std_array<T>::value || is_std_vector<T>::value || is_std_set<T>::value || is_std_unordered_set<T>::value)
                {
                    if (!value.empty())
                    {
                        context.append_char('{');
                        to_string_join(context, true, fmtspec, value, ", ", 2);
                        context.append_char('}');
                    }
                }
                // std::map / std::unordered_map
                else if constexpr (is_std_map<T>::value || is_std_unordered_map<T>::value)
                {
                    if (!value.empty())
                    {
                        context.append_str("{{", 2);
                        auto it = value.begin();
                        to_string(context, true, index, fmtspec, it->first);
                        context.append_str(", ", 2);
                        to_string(context, true, index, fmtspec, it->second);
                        context.append_char('}');
                        for (++it; it != value.end(); ++it)
                        {
                            context.append_str(", {", 3);
                            to_string(context, true, index, fmtspec, it->first);
                            context.append_str(", ", 2);
                            to_string(context, true, index, fmtspec, it->second);
                            context.append_char('}');
                        }
                        context.append_char('}');
                    }
                }
                else 
                {
                    // try custom formatter
                    try 
                    {
                        to_string(context, fmtspec, value);
                    }
                    catch (...)
                    {
                        format_param_error<T>("unsupported parameter type", index);
                    }
                }
            }

            template <typename T>
            inline void to_string_join(fmt_context& context, bool inner, const char* fmtspec, const T& value, const char* sep, int sepsize)
            {
                // std::pair
                if constexpr (is_std_pair<T>::value)
                {
                    to_string(context, inner, -1, fmtspec, value.first);
                    context.append_str(sep, sepsize);
                    to_string(context, inner, -1, fmtspec, value.second);
                }
                // std::array
                else if constexpr (is_std_array<T>::value)
                {
                    if (!value.empty())
                    {
                        auto it = value.begin();
                        to_string(context, inner, -1, fmtspec, *it);
                        for (++it; it != value.end(); ++it)
                        {
                            context.append_str(sep, sepsize);
                            to_string(context, inner, -1, fmtspec, *it);
                        }
                    }
                }
                // std::vector / std::set / std::unordered_set
                else if constexpr (is_std_vector<T>::value || is_std_set<T>::value || is_std_unordered_set<T>::value)
                {
                    if (!value.empty())
                    {
                        auto it = value.begin();
                        to_string(context, inner, -1, fmtspec, *it);
                        for (++it; it != value.end(); ++it)
                        {
                            context.append_str(sep, sepsize);
                            to_string(context, inner, -1, fmtspec, *it);
                        }
                    }
                }
                else 
                {
                    // try custom formatter
                    try 
                    {
                        to_string_join(context, fmtspec, value, sep, sepsize);
                    }
                    catch (...)
                    {
                        format_param_error<T>("unsupported parameter type", -1);
                    }
                }
            }

            template <typename T, typename Formatter>
            inline void to_string_join_formatter(fmt_context& context, const T& value, const char* sep, int sepsize, Formatter formatter)
            {
                // std::array
                if constexpr (is_std_array<T>::value)
                {
                    if (!value.empty())
                    {
                        auto it = value.begin();
                        formatter(context, *it);
                        for (++it; it != value.end(); ++it)
                        {
                            context.append_str(sep, sepsize);
                            formatter(context, *it);
                        }
                    }
                }
                // std::vector / std::set / std::unordered_set
                else if constexpr (is_std_vector<T>::value || is_std_set<T>::value || is_std_unordered_set<T>::value)
                {
                    if (!value.empty())
                    {
                        auto it = value.begin();
                        formatter(context, *it);
                        for (++it; it != value.end(); ++it)
                        {
                            context.append_str(sep, sepsize);
                            formatter(context, *it);
                        }
                    }
                }
                else 
                {
                    format_param_error<T>("formatting with a custom formatter is not currently supported for type", -1);
                }
            }

            /*
            ----------------------------------- step 1: parse format string -----------------------------------
            Here we implement a small DFA:
            init: startpos = 0
            S0: waiting for '{'. 
                Encounter '{' -> write [startpos, pos - 1], S1
                Encounter '}' -> write [startpos, pos - 1], S3
                Encounter other -> S0

            S1: has encountered '{'. 
                Encounter '{' -> startpos = pos, S0
                Encounter '}' -> startpos = pos + 1, format string, S0
                Encounter ':' -> specstart = pos + 1, S2
                Encounter other -> error

            S2: parsing format specifier.
                Encounter '}' -> startpos = pos + 1, fmtspec = %[specstart, pos - 1], format string, S0
                Encounter other -> S2

            S3: found '}', must find another '}'
                Encounter '}' -> startpos = pos, S0
                Encounter other -> error

            ASCII:
            '}' -> 125, 7D, 0111 1101
            ':' ->  58, 3A, 0011 1010
            '{' -> 123, 7B, 0111 1011
            */

            class parse_context
            {
            private:
                // the start iterating pos of fmt string
                char* fmtbegin;
                // the current iterating pos of fmt string
                char* fmtpos;
                // the starting position that has to write to buffer
                int startpos;
                // the starting position of format specifier
                int specstart;
                // format specifier (short / long)
                // when its length are shorter than 32, we use fmtspec_short; otherwise we use fmtspec_long
                char fmtspec_short[32];
                std::string fmtspec_long;
                char* fmtspec;

                // parse until finding the next format position
                // if found, return 0; if not found, return 1
                int next_internal(fmt_context& context)
                {
                    while (true)
                    {
                        // iterate until encounter '}' or '{'
                        // we do a simple check first, by comparing it with '{'
                        while ((*fmtpos) && (*fmtpos) < '{')
                            ++fmtpos;
                        // if we cannot find '}', then break
                        if (!(*fmtpos))
                            break;
                        // S0 -> S1
                        if ((*fmtpos) == '{')
                        {
                            // write [startpos, pos - 1] to buffer
                            int pos = static_cast<int>(fmtpos - fmtbegin);
                            context.append_str(fmtbegin + startpos, pos - startpos);
                            ++fmtpos;
                            if (!(*fmtpos))
                                format_parse_error(fmtbegin, "unterminated '{'", pos);
                            if ((*fmtpos) == '}')
                            {
                                // startpos = pos + 2, fmtspec = nullptr and format one parameter
                                startpos = pos + 2;
                                fmtspec = nullptr;
                                ++fmtpos;
                                return 0;
                            }
                            else if ((*fmtpos) == '{')
                            {
                                // startpos = pos + 1, and return to S0
                                startpos = pos + 1;
                                ++fmtpos;
                                continue;
                            }
                            // S1 -> S2
                            else if ((*fmtpos) == ':')
                            {
                                // specstart = pos + 2, and switch to S2
                                specstart = pos + 2;
                                // find the position of '}'
                                while ((*fmtpos) && (*fmtpos) != '}')
                                    ++fmtpos;
                                if (!(*fmtpos))
                                    format_parse_error(fmtbegin, "unterminated '{'", pos);
                                // startpos = endpos + 1, fmtspec = % + [specstart, endpos - 1], and format one parameter
                                int endpos = static_cast<int>(fmtpos - fmtbegin);
                                ++fmtpos;
                                startpos = endpos + 1;
                                int len = endpos - specstart;
                                // if fmtspec's length are no longer than 30, then we use simple memcpy to copy fmtspec
                                if (len <= 30)
                                {
                                    std::memcpy(fmtspec_short + 1, fmtbegin + specstart, len);
                                    // add null termination to fmtspec
                                    fmtspec_short[len + 1] = '\0';
                                    fmtspec = fmtspec_short;
                                }
                                else
                                {
                                    fmtspec_long = "%" + std::string(fmtbegin + specstart, len);
                                    fmtspec = fmtspec_long.data();
                                }
                                return 0;
                            }
                            else 
                                format_parse_error(fmtbegin, "contents before ':' such as positional information are not supported", pos + 1);
                        }
                        // S0 -> S3
                        else if ((*fmtpos) == '}')
                        {
                            // write [startpos, pos - 1] to buffer
                            int pos = static_cast<int>(fmtpos - fmtbegin);
                            context.append_str(fmtbegin + startpos, pos - startpos);
                            ++fmtpos;
                            if (!(*fmtpos) || (*fmtpos) != '}')
                                format_parse_error(fmtbegin, "unmatched '}'", pos);
                            // set startpos = pos + 1, and return to S0
                            startpos = pos + 1;
                            ++fmtpos;
                        }
                        else 
                            ++fmtpos;
                    }
                    // in the end, status = 0, write [startpos, pos - 1] to buffer
                    int pos = static_cast<int>(fmtpos - fmtbegin);
                    context.append_str(fmtbegin + startpos, pos - startpos);
                    startpos = pos;
                    return 1;
                }

            public:
                parse_context(const std::string& fmt) : 
                    fmtbegin(const_cast<char*>(fmt.data())), fmtpos(const_cast<char*>(fmt.data())), startpos(0), fmtspec_short("%") {}
                
                parse_context(const char* fmt) : 
                    fmtbegin(const_cast<char*>(fmt)), fmtpos(const_cast<char*>(fmt)), startpos(0), fmtspec_short("%") {}

                // parse until finding the next format position
                // if found, return; if not found, report error
                template <typename T>
                void next(fmt_context& context, int paramidx)
                {
                    if (!next_internal(context))
                        return;
                    format_param_error<T>("excessive parameter", paramidx);
                }

                // fill the remaining string
                void fill_remain(fmt_context& context)
                {
                    // judge whether there are any character like '{' and '}'
                    while (true)
                    {
                        while ((*fmtpos) && (*fmtpos) < '{')
                            ++fmtpos;
                        if (!(*fmtpos))
                            break;
                        // if fmt[pos] == '{' || fmt[pos] == '}', but fmt[pos + 1] == fmt[pos], then it means '{{' or '}}', which is accepted;
                        // otherwise, it means there are more '{}' than expected
                        char orig = (*fmtpos);
                        int pos = static_cast<int>(fmtpos - fmtbegin);
                        if (orig == '{' || orig == '}')
                        {
                            ++fmtpos;
                            if ((*fmtpos) != orig)
                                format_parse_error(fmtbegin, "excessive '{'", pos);
                            // write [startpos, pos - 1] to the buffer
                            context.append_str(fmtbegin + startpos, pos - startpos);
                            // set startpos = pos + 1
                            startpos = pos + 1;
                            ++fmtpos;
                            continue;
                        }
                        ++fmtpos;
                    }
                    // in the end, write [startpos, pos - 1] to buffer
                    context.append_str(fmtbegin + startpos, static_cast<int>(fmtpos - fmtbegin) - startpos);
                }

                // return the format specifier
                const char* spec() const { return fmtspec; }
            };

            // format one argument
            template <typename T>
            inline void format_arg(fmt_context& context, parse_context& pcontext, int index, const T& value)
            {
                pcontext.next<T>(context, index);
                to_string(context, false, index, pcontext.spec(), value);
            }

            template <typename... Args>
            inline void format_to(fmt_context& context, const std::string& fmt, Args&&... args)
            {
                // create parse context
                parse_context pcontext(fmt);
                // format each argument
                int index = 0;
                ((format_arg(context, pcontext, index++, std::forward<Args>(args))), ...);
                // add remaining text to the buffer
                pcontext.fill_remain(context);
            }

            // format implementation (const char* version)
            template <typename... Args>
            inline void format_to(fmt_context& context, const char* fmt, Args&&... args)
            {
                // create parse context
                parse_context pcontext(fmt);
                // format each argument
                int index = 0;
                ((format_arg(context, pcontext, index++, std::forward<Args>(args))), ...);
                // add remaining text to the buffer
                pcontext.fill_remain(context);
            }

            // ----------------------------------------- report format errors (implementation) ----------------------------------------------
            // report general error
            inline void format_error(const char* errmsg)
            {
                throw std::runtime_error(errmsg);
            }
            // report parameter error
            inline void format_param_error_internal(const char* errmsg, int paramidx, const char* name) 
            {
                // initial buffer
                char buf[initbufsize];
                // create format context
                fmt_context context(buf, initbufsize, true);
                // call implementation
                #ifndef _MSC_VER
                if (paramidx != -1)
                    format_to(context, "format param error: {} {} at location {}", errmsg, abi::__cxa_demangle(name, nullptr, nullptr, nullptr), paramidx);
                else 
                    format_to(context, "format param error: {} {}", errmsg, abi::__cxa_demangle(name, nullptr, nullptr, nullptr));
                #else 
                if (paramidx != -1)
                    format_to(context, "format param error: {} {} at location {}", errmsg, name, paramidx);
                else 
                    format_to(context, "format param error: {} {}", errmsg, name);
                #endif
                context.eof();
                // throw exception
                throw std::runtime_error(context.data());
            }            
            inline void format_param_error_internal(const char* errmsg, int errcode, int paramidx, const char* name)
            {
                // initial buffer
                char buf[initbufsize];
                // create format context
                fmt_context context(buf, initbufsize, true);
                // call implementation
                #ifndef _MSC_VER
                if (paramidx != -1)
                    format_to(context, "format param error: {} with error code {} for type {} at location {}", errmsg, errcode, abi::__cxa_demangle(name, nullptr, nullptr, nullptr), paramidx);
                else 
                    format_to(context, "format param error: {} with error code {} for type {}", errmsg, errcode, abi::__cxa_demangle(name, nullptr, nullptr, nullptr));
                #else
                if (paramidx != -1)
                    format_to(context, "format param error: {} with error code {} for type {} at location {}", errmsg, errcode, name, paramidx);
                else 
                    format_to(context, "format param error: {} with error code {} for type {}", errmsg, errcode, name);
                #endif
                context.eof();
                // throw exception
                throw std::runtime_error(context.data());
            }
            // report format string parse error
            inline void format_parse_error(const std::string& fmt, const char* errmsg, int idx)
            {
                // create locator
                std::string locator(fmt);
                std::replace_if(locator.begin(), locator.end(), [](char c) { return c != '\n'; }, '~');
                locator[idx] = '^';

                // initial buffer
                char buf[initbufsize];
                // create format context
                fmt_context context(buf, initbufsize, true);
                // call implementation
                format_to(context, "format parse error: {} at column {}\n{}\n{}", errmsg, idx, fmt, locator);
                context.eof();
                // throw exception
                throw std::runtime_error(context.data());
            }
        }
    }
}