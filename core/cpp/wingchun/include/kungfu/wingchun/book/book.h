/**
 * This is source code modified under the Apache License 2.0.
 * Original Author: Keren Dong
 * Modifier: kx@godzilla.dev
 * Modification date: March 3, 2025
 */

#ifndef KUNGFU_WINGCHUN_BOOK_H
#define KUNGFU_WINGCHUN_BOOK_H

#include <kungfu/practice/apprentice.h>
#include <kungfu/wingchun/msg.h>

namespace kungfu
{
    namespace wingchun
    {
        namespace book
        {
            FORWARD_DECLARE_PTR(BookContext)

            class Book
            {
            public:
                Book(): ready_(false) {}

                virtual void on_depth(yijinjing::event_ptr event, const msg::data::Depth &depth) = 0;

                virtual void on_trade(yijinjing::event_ptr event, const msg::data::MyTrade &trade) = 0;

                virtual void on_order(yijinjing::event_ptr event, const msg::data::Order &order) = 0;

                virtual void on_order_input(yijinjing::event_ptr event, const msg::data::OrderInput &input) = 0;

                virtual void on_position(yijinjing::event_ptr event, const msg::data::Position& position) = 0;

                virtual void on_asset(yijinjing::event_ptr event, const msg::data::Asset& asset) = 0;

                virtual ~Book() = default;

                bool is_ready() const { return ready_; }

            private:
                bool ready_;

                friend class BookContext;
            };

            DECLARE_PTR(Book)

            class BookContext
            {
            public:
                explicit BookContext(practice::apprentice &app, const rx::connectable_observable<yijinjing::event_ptr> &events);

                ~BookContext() = default;

                void add_book(const yijinjing::data::location_ptr& location, const Book_ptr& book);

                void pop_book(uint32_t location_uid);

                void monitor_instruments();

                const msg::data::Instrument& get_inst_info(const std::string &symbol, const std::string &exchange_id) const;

                std::vector<msg::data::Instrument> all_inst_info() const;

            private:
                void monitor_positions(const yijinjing::data::location_ptr& location, const Book_ptr& book);

                void monitor_position_details(const yijinjing::data::location_ptr& location, const Book_ptr& book);

                practice::apprentice &app_;

                const rx::connectable_observable<yijinjing::event_ptr> &events_;

                yijinjing::data::location_ptr service_location_;

                std::unordered_map<uint32_t, msg::data::Instrument> instruments_;

                std::unordered_map<uint32_t, std::set<Book_ptr>> books_;
            };
        }
    }
}

#endif //KUNGFU_WINGCHUN_BOOK_H
