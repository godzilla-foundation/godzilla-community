
// ----------------------------------------------------------------------------
//                              Apache License
//                        Version 2.0, January 2004
//                     http://www.apache.org/licenses/
//
// This file is part of binapi(https://github.com/niXman/binapi) project.
//
// Copyright (c) 2019-2021 niXman (github dot nixman dog pm.me). All rights reserved.
// ----------------------------------------------------------------------------

#ifndef __binapi__websocket_hpp
#define __binapi__websocket_hpp

#include "enums.hpp"

#include <memory>
#include <functional>

namespace boost {
namespace asio {
class io_context;
} // ns asio
} // ns boost

namespace binapi {
namespace userdata {

struct account_update_t;
struct balance_update_t;
struct order_update_t;
struct future_order_update_t;

} // ns userdata

namespace ws {

struct part_depths_t;
struct diff_depths_t;
struct trade_t;
struct agg_trade_t;
struct kline_t;
struct mini_ticker_t;
struct mini_tickers_t;
struct market_ticker_t;
struct markets_tickers_t;
struct book_ticker_t;
struct future_part_depths_t;
struct mark_price_t;

/*************************************************************************************************/

struct websockets {
    websockets(const websockets &) = delete;
    websockets& operator= (const websockets &) = delete;
    websockets(websockets &&) noexcept = default;
    websockets& operator= (websockets &&) noexcept = default;

    using on_message_received_cb = std::function<void(const char *channel, const char *ptr, std::size_t size)>;

    websockets(
         boost::asio::io_context &ioctx
        ,std::string host
        ,std::string port
        ,on_message_received_cb cb = {}
    );
    ~websockets();

    using handle = void *;

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#partial-book-depth-streams
    using on_part_depths_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, part_depths_t msg)>;
    handle part_depth(const char *pair, e_levels level, e_freq freq, on_part_depths_received_cb cb);
    // https://binance-docs.github.io/apidocs/futures/cn/#6ae7c2b506
    handle future_part_depth(const char *pair, e_levels level, e_freq freq, on_part_depths_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#diff-depth-stream
    using on_diff_depths_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, diff_depths_t msg)>;
    handle diff_depth(const char *pair, e_freq freq, on_diff_depths_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#klinecandlestick-streams
    using on_kline_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, kline_t msg)>;
    // period - 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
    handle klines(const char *pair, const char *period, on_kline_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#trade-streams
    using on_trade_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, trade_t msg)>;
    handle trade(const char *pair, on_trade_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#aggregate-trade-streams
    using on_agg_trade_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, agg_trade_t msg)>;
    handle agg_trade(const char *pair, on_agg_trade_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#individual-symbol-mini-ticker-stream
    using on_mini_ticker_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, mini_ticker_t msg)>;
    handle mini_ticker(const char *pair, on_mini_ticker_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#all-market-mini-tickers-stream
    using on_mini_tickers_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, mini_tickers_t msg)>;
    handle mini_tickers(on_mini_tickers_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#individual-symbol-ticker-streams
    using on_market_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, market_ticker_t msg)>;
    handle market(const char *pair, on_market_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#all-market-tickers-stream
    using on_markets_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, markets_tickers_t msg)>;
    handle markets(on_markets_received_cb cb);

    // https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#individual-symbol-book-ticker-streams
    using on_book_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, book_ticker_t msg)>;
    handle book(const char *pair, on_book_received_cb cb);

    using on_books_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, book_ticker_t msg)>;
    handle books(on_books_received_cb cb);

    // https://binance-docs.github.io/apidocs/delivery/cn/#markprice
    using on_mark_price_received_cb = std::function<bool(const char *fl, int ec, std::string errmsg, mark_price_t msg)>;
    handle mark_price(const char *pair, on_mark_price_received_cb cb);

    using on_account_update_cb = std::function<bool(const char *fl, int ec, std::string errmsg, userdata::account_update_t msg)>;
    using on_balance_update_cb = std::function<bool(const char *fl, int ec, std::string errmsg, userdata::balance_update_t msg)>;
    using on_order_update_cb = std::function<bool(const char *fl, int ec, std::string errmsg, userdata::order_update_t msg)>;
    handle userdata(
         const char *lkey
        ,on_account_update_cb account_update
        ,on_balance_update_cb balance_update
        ,on_order_update_cb order_update
    );

    using future_order_update_cb = std::function<bool(const char *fl, int ec, std::string errmsg, userdata::future_order_update_t msg)>;
    handle future_order_data(
         const char *lkey
        ,future_order_update_cb
    );

    void unsubscribe(const handle &h);
    void async_unsubscribe(const handle &h);
    void unsubscribe_all();
    void async_unsubscribe_all();
    bool fetch_reconnect_flag();
    bool is_ready(websockets::handle h);

private:
    struct impl;
    std::unique_ptr<impl> pimpl;
};

/*************************************************************************************************/

} // ns ws
} // ns binapi

#endif // __binapi__websocket_hpp
