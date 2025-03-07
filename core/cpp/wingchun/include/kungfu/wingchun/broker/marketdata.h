/**
 * This is source code modified under the Apache License 2.0.
 * Original Author: Keren Dong
 * Modifier: kx@godzilla.dev
 * Modification date: March 3, 2025
 */

#ifndef WINGCHUN_MARKETDATA_H
#define WINGCHUN_MARKETDATA_H

#include <kungfu/yijinjing/log/setup.h>
#include <kungfu/yijinjing/io.h>
#include <kungfu/practice/apprentice.h>
#include <kungfu/wingchun/msg.h>

namespace kungfu
{
    namespace wingchun
    {
        namespace broker
        {
            class MarketData : public practice::apprentice
            {
            public:
                explicit MarketData(bool low_latency, yijinjing::data::locator_ptr locator, const std::string &source);

                virtual ~MarketData() = default;

                virtual void on_start() override;

                virtual bool subscribe(const std::vector<msg::data::Instrument> &instruments) = 0;

                virtual bool subscribe_trade(const std::vector<msg::data::Instrument> &instruments) = 0;

                virtual bool subscribe_ticker(const std::vector<msg::data::Instrument> &instruments) = 0;

                virtual bool subscribe_index_price(const std::vector<msg::data::Instrument> &instruments) = 0;

                virtual bool subscribe_all() = 0;

                virtual bool unsubscribe(const std::vector<msg::data::Instrument> &instruments) = 0;

            protected:
                void publish_state(msg::data::BrokerState state)
                {
                    auto s = static_cast<int32_t>(state);
                    write_to(0, msg::type::BrokerState, s);
                }
            };
        }
    }
}

#endif //WINGCHUN_MARKETDATA_H
