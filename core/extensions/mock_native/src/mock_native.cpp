#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <kungfu/yijinjing/log/setup.h>
#include <kungfu/yijinjing/time.h>
#include <kungfu/wingchun/broker/marketdata.h>
#include <kungfu/wingchun/broker/trader.h>
#include <kungfu/wingchun/msg.h>

namespace py = pybind11;

using namespace kungfu;
using namespace kungfu::wingchun;
using namespace kungfu::wingchun::broker;
using namespace kungfu::wingchun::msg::data;

namespace
{
    constexpr const char *SOURCE_MOCK = "mock";
    constexpr const char *DEFAULT_SYMBOL = "BTC-USDT";
    constexpr const char *DEFAULT_EXCHANGE = "mock";

    int64_t env_i64(const char *name, int64_t fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::atoll(value);
    }

    int env_int(const char *name, int fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::atoi(value);
    }

    std::string env_string(const char *name, const std::string &fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::string(value);
    }

    void copy_text(char *dst, size_t dst_size, const std::string &src)
    {
        if (dst_size == 0)
        {
            return;
        }
        std::memset(dst, 0, dst_size);
        std::strncpy(dst, src.c_str(), dst_size - 1);
    }
}

class MockNativeMarketData : public MarketData
{
public:
    MockNativeMarketData(bool low_latency, yijinjing::data::locator_ptr locator, const std::string &json_config)
        : MarketData(low_latency, std::move(locator), SOURCE_MOCK),
          interval_ns_(std::max<int64_t>(1, env_i64("GZ_MOCK_MD_INTERVAL_NS", 1000000))),
          max_batch_(std::max(1, env_int("GZ_MOCK_MD_MAX_BATCH", 1))),
          max_events_(std::max<int64_t>(0, env_i64("GZ_MOCK_MD_MAX_EVENTS", 0))),
          spin_ns_(std::max<int64_t>(0, env_i64("GZ_MOCK_MD_SPIN_NS", 0))),
          default_symbol_(env_string("GZ_MOCK_MD_SYMBOL", DEFAULT_SYMBOL)),
          default_exchange_(env_string("GZ_MOCK_MD_EXCHANGE", DEFAULT_EXCHANGE))
    {
        (void)json_config;
        yijinjing::log::copy_log_settings(get_io_device()->get_home(), "mock_native");
    }

    void on_start() override
    {
        MarketData::on_start();
        publish_state(BrokerState::Ready);
        running_.store(true);
        publisher_thread_ = std::thread([this] { publish_loop(); });
        SPDLOG_INFO("mock native md benchmark mode enabled local_thread=1 interval_ns={} max_batch={} max_events={} spin_ns={}", interval_ns_, max_batch_, max_events_, spin_ns_);
    }

    void on_exit() override
    {
        running_.store(false);
        if (publisher_thread_.joinable())
        {
            publisher_thread_.join();
        }
        MarketData::on_exit();
    }

    bool subscribe(const std::vector<Instrument> &instruments) override
    {
        for (const auto &inst : instruments)
        {
            std::string symbol(inst.symbol);
            if (symbol.empty())
            {
                symbol = default_symbol_;
            }
            {
                std::lock_guard<std::mutex> lock(symbols_mutex_);
                subscribed_symbols_.insert(symbol);
                instrument_types_[symbol] = inst.instrument_type;
                std::string exchange(inst.exchange_id);
                if (!exchange.empty())
                {
                    exchange_ids_[symbol] = exchange;
                }
            }
            if (subscribe_log_count_ < 3)
            {
                SPDLOG_INFO("mock native md subscribed {}", symbol);
                subscribe_log_count_++;
            }
        }
        return true;
    }

    bool subscribe_trade(const std::vector<Instrument> &instruments) override
    {
        (void)instruments;
        return true;
    }

    bool subscribe_ticker(const std::vector<Instrument> &instruments) override
    {
        (void)instruments;
        return true;
    }

    bool subscribe_index_price(const std::vector<Instrument> &instruments) override
    {
        (void)instruments;
        return true;
    }

    bool subscribe_all() override
    {
        std::lock_guard<std::mutex> lock(symbols_mutex_);
        subscribed_symbols_.insert(default_symbol_);
        instrument_types_[default_symbol_] = InstrumentType::Spot;
        exchange_ids_[default_symbol_] = default_exchange_;
        return true;
    }

    bool unsubscribe(const std::vector<Instrument> &instruments) override
    {
        for (const auto &inst : instruments)
        {
            std::string symbol(inst.symbol);
            std::lock_guard<std::mutex> lock(symbols_mutex_);
            subscribed_symbols_.erase(symbol);
            instrument_types_.erase(symbol);
            exchange_ids_.erase(symbol);
        }
        return true;
    }

private:
    void publish_loop()
    {
        auto next = std::chrono::steady_clock::now();
        while (running_.load())
        {
            publish_next();
            next += std::chrono::nanoseconds(interval_ns_);
            wait_until_next(next);
            const auto now = std::chrono::steady_clock::now();
            if (now > next + std::chrono::milliseconds(10))
            {
                next = now;
            }
        }
    }

    void wait_until_next(const std::chrono::steady_clock::time_point &next) const
    {
        if (spin_ns_ <= 0)
        {
            std::this_thread::sleep_until(next);
            return;
        }
        const auto spin = std::chrono::nanoseconds(std::min<int64_t>(spin_ns_, interval_ns_));
        const auto sleep_target = next - spin;
        const auto now = std::chrono::steady_clock::now();
        if (now < sleep_target)
        {
            std::this_thread::sleep_until(sleep_target);
        }
        while (running_.load(std::memory_order_relaxed) && std::chrono::steady_clock::now() < next)
        {
        }
    }

    void publish_next()
    {
        std::string symbol;
        InstrumentType instrument_type = InstrumentType::Spot;
        std::string exchange;
        {
            std::lock_guard<std::mutex> lock(symbols_mutex_);
            if (subscribed_symbols_.empty())
            {
                return;
            }
            symbol = pick_symbol_unlocked();
            instrument_type = pick_instrument_type_unlocked(symbol);
            exchange = pick_exchange_unlocked(symbol);
        }
        auto writer = get_writer(0);
        for (int i = 0; i < max_batch_; ++i)
        {
            if (max_events_ > 0 && event_id_ >= max_events_)
            {
                running_.store(false);
                return;
            }
            const int64_t event_id = ++event_id_;
            Depth &depth = writer->open_data<Depth>(0, msg::type::Depth);
            std::memset(&depth, 0, sizeof(Depth));
            copy_text(depth.source_id, sizeof(depth.source_id), SOURCE_MOCK);
            copy_text(depth.symbol, sizeof(depth.symbol), symbol);
            copy_text(depth.exchange_id, sizeof(depth.exchange_id), exchange);
            depth.data_time = event_id;
            depth.instrument_type = instrument_type;

            const double mid = 65000.0 + static_cast<double>(event_id % 100) * 0.01;
            for (int level = 0; level < 10; ++level)
            {
                const double offset = static_cast<double>(level + 1) * 0.1;
                depth.bid_price[level] = mid - offset;
                depth.ask_price[level] = mid + offset;
                depth.bid_volume[level] = 0.001 * static_cast<double>(level + 1);
                depth.ask_volume[level] = 0.001 * static_cast<double>(level + 1);
            }
            writer->close_data();
            if (publish_log_count_ < 3)
            {
                SPDLOG_INFO("mock native md published event_id={} symbol={}", event_id, symbol);
                publish_log_count_++;
            }
        }
    }

    std::string pick_symbol_unlocked() const
    {
        if (subscribed_symbols_.find(default_symbol_) != subscribed_symbols_.end())
        {
            return default_symbol_;
        }
        return *subscribed_symbols_.begin();
    }

    InstrumentType pick_instrument_type_unlocked(const std::string &symbol) const
    {
        auto it = instrument_types_.find(symbol);
        if (it == instrument_types_.end() || it->second == InstrumentType::Unknown)
        {
            return InstrumentType::Spot;
        }
        return it->second;
    }

    std::string pick_exchange_unlocked(const std::string &symbol) const
    {
        auto it = exchange_ids_.find(symbol);
        if (it == exchange_ids_.end() || it->second.empty())
        {
            return default_exchange_;
        }
        return it->second;
    }

    int64_t interval_ns_;
    int max_batch_;
    int64_t max_events_;
    int64_t spin_ns_;
    int64_t event_id_ = 0;
    int publish_log_count_ = 0;
    int subscribe_log_count_ = 0;
    std::atomic<bool> running_{false};
    std::thread publisher_thread_;
    std::string default_symbol_;
    std::string default_exchange_;
    std::mutex symbols_mutex_;
    std::set<std::string> subscribed_symbols_;
    std::map<std::string, InstrumentType> instrument_types_;
    std::map<std::string, std::string> exchange_ids_;
};

class MockNativeTrader : public Trader
{
public:
    MockNativeTrader(bool low_latency, yijinjing::data::locator_ptr locator, const std::string &account_id, const std::string &json_config)
        : Trader(low_latency, std::move(locator), SOURCE_MOCK, account_id)
    {
        (void)json_config;
        yijinjing::log::copy_log_settings(get_io_device()->get_home(), "mock_native");
    }

    AccountType get_account_type() const override
    {
        return AccountType::Stock;
    }

    void on_start() override
    {
        Trader::on_start();
        publish_state(BrokerState::Ready);
        SPDLOG_INFO("mock native td no-socket benchmark mode enabled");
    }

    bool insert_order(const yijinjing::event_ptr &event) override
    {
        const OrderInput &input = event->data<OrderInput>();
        const int64_t now = yijinjing::time::now_in_nano();
        auto writer = get_writer(event->source());
        Order &order = writer->open_data<Order>(now, msg::type::Order);
        order_from_input(input, order);
        order.insert_time = now;
        order.update_time = now;
        order.status = OrderStatus::Submitted;
        order.volume_left = order.volume - order.volume_traded;
        writer->close_data();
        return true;
    }

    bool cancel_order(const yijinjing::event_ptr &event) override
    {
        (void)event;
        return true;
    }

    bool query_order(const yijinjing::event_ptr &event) override
    {
        (void)event;
        return true;
    }

    bool req_position() override
    {
        return false;
    }

    bool req_account() override
    {
        return false;
    }
};

PYBIND11_MODULE(kfext_mock_native, m)
{
    py::class_<MockNativeMarketData, kungfu::practice::apprentice, std::shared_ptr<MockNativeMarketData>>(m, "MD")
        .def(py::init<bool, yijinjing::data::locator_ptr, const std::string &>())
        .def("run", &MockNativeMarketData::run, py::call_guard<py::gil_scoped_release>());

    py::class_<MockNativeTrader, kungfu::practice::apprentice, std::shared_ptr<MockNativeTrader>>(m, "TD")
        .def(py::init<bool, yijinjing::data::locator_ptr, const std::string &, const std::string &>())
        .def("run", &MockNativeTrader::run, py::call_guard<py::gil_scoped_release>());
}
