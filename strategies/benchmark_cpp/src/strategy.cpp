//
// Native benchmark strategy.
//

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <string>
#include <utility>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <kungfu/yijinjing/log/setup.h>
#include <kungfu/wingchun/msg.h>
#include <kungfu/wingchun/strategy/context.h>
#include <kungfu/wingchun/strategy/strategy.h>

namespace py = pybind11;

using namespace kungfu;
using namespace kungfu::wingchun;
using namespace kungfu::wingchun::strategy;

namespace
{
    static int64_t now_ns()
    {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
                   std::chrono::steady_clock::now().time_since_epoch())
            .count();
    }

    static std::string env_value(const char *name, const std::string &fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::string(value);
    }

    static int env_int(const char *name, int fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::atoi(value);
    }

    static double env_double(const char *name, double fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        return std::atof(value);
    }

    static bool env_bool(const char *name, bool fallback)
    {
        const char *value = std::getenv(name);
        if (value == nullptr || *value == '\0')
        {
            return fallback;
        }
        std::string text(value);
        for (auto &ch : text)
        {
            ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        }
        return text == "1" || text == "true" || text == "yes" || text == "on";
    }

    static const char *side_name(Side side)
    {
        switch (side)
        {
        case Side::Buy:
            return "BUY";
        case Side::Sell:
            return "SELL";
        default:
            return "UNKNOWN";
        }
    }

    class TraceWriter
    {
    public:
        virtual ~TraceWriter() = default;
        virtual void write_row(
            const std::string &run_id,
            const std::string &system,
            int64_t event_id,
            const std::string &symbol,
            const std::string &side,
            uint64_t order_id,
            const std::string &client_order_id,
            const std::string &t_exchange_emit_ns,
            const std::string &t_msg_received_ns,
            int64_t t_strategy_visible_ns,
            int64_t t_strategy_triggered_ns,
            int64_t t_order_constructed_ns) = 0;
        virtual void close() = 0;
    };

    class CsvTraceWriter : public TraceWriter
    {
    public:
        explicit CsvTraceWriter(const std::string &path)
            : out_(path, std::ios::app)
        {
            if (!out_.is_open())
            {
                throw std::runtime_error("failed to open benchmark trace file: " + path);
            }
            out_.seekp(0, std::ios::end);
            if (out_.tellp() == 0)
            {
                out_ << "run_id,system,event_id,symbol,side,order_id,client_order_id,t_exchange_emit_ns,t_msg_received_ns,t_strategy_visible_ns,t_strategy_triggered_ns,t_order_constructed_ns,decision_ns\n";
            }
        }

        void write_row(
            const std::string &run_id,
            const std::string &system,
            int64_t event_id,
            const std::string &symbol,
            const std::string &side,
            uint64_t order_id,
            const std::string &client_order_id,
            const std::string &t_exchange_emit_ns,
            const std::string &t_msg_received_ns,
            int64_t t_strategy_visible_ns,
            int64_t t_strategy_triggered_ns,
            int64_t t_order_constructed_ns) override
        {
            out_ << run_id << ','
                 << system << ','
                 << event_id << ','
                 << symbol << ','
                 << side << ','
                 << order_id << ','
                 << client_order_id << ','
                 << t_exchange_emit_ns << ','
                 << t_msg_received_ns << ','
                 << t_strategy_visible_ns << ','
                 << t_strategy_triggered_ns << ','
                 << t_order_constructed_ns << ','
                 << (t_order_constructed_ns - t_strategy_triggered_ns) << '\n';
        }

        void close() override
        {
            if (out_.is_open())
            {
                out_.flush();
                out_.close();
            }
        }

    private:
        std::ofstream out_;
    };

    class NullTraceWriter : public TraceWriter
    {
    public:
        void write_row(
            const std::string &,
            const std::string &,
            int64_t,
            const std::string &,
            const std::string &,
            uint64_t,
            const std::string &,
            const std::string &,
            const std::string &,
            int64_t,
            int64_t,
            int64_t) override
        {
        }

        void close() override
        {
        }
    };
} // namespace

class BenchmarkStrategy : public Strategy
{
public:
    explicit BenchmarkStrategy(yijinjing::data::location_ptr home)
        : home_(std::move(home)),
          symbol_(env_value("GZ_BENCH_SYMBOL", "BTC-USDT")),
          source_(env_value("GZ_BENCH_MD_SOURCE", "mock")),
          exchange_(env_value("GZ_BENCH_EXCHANGE", "mock")),
          account_(env_value("GZ_BENCH_ACCOUNT", "benchmark")),
          run_id_(env_value("GZ_BENCH_RUN_ID", "local")),
          trace_mode_(env_value("GZ_BENCH_TRACE_MODE", "buffered")),
          trace_path_(env_value("GZ_BENCH_TRACE_PATH", "traces/raw/simple_benchmark_strategy.csv")),
          qty_(env_double("GZ_BENCH_QTY", 0.001)),
          max_orders_(env_int("GZ_BENCH_MAX_ORDERS", 1000)),
          alternate_side_(env_bool("GZ_BENCH_ALTERNATE_SIDE", true))
    {
        yijinjing::log::copy_log_settings(home_, "benchmark_cpp");
        if (trace_mode_ == "off" || trace_mode_ == "none" || trace_mode_ == "disabled" || trace_mode_ == "journal")
        {
            trace_ = std::unique_ptr<TraceWriter>(new NullTraceWriter());
        }
        else
        {
            trace_ = std::unique_ptr<TraceWriter>(new CsvTraceWriter(trace_path_));
        }
    }

    void pre_start(Context_ptr context) override
    {
        context->add_account(source_, account_);
        context->subscribe(source_, {symbol_}, InstrumentType::Spot, exchange_);
        SPDLOG_INFO("benchmark cpp pre_start symbol={} source={} exchange={} account={}", symbol_, source_, exchange_, account_);
    }

    void pre_stop(Context_ptr context) override
    {
        (void)context;
        trace_->close();
    }

    void on_depth(Context_ptr context, const msg::data::Depth &depth) override
    {
        if (symbol_ != depth.get_symbol())
        {
            return;
        }
        if (orders_ >= max_orders_)
        {
            return;
        }

        const int64_t t_strategy_visible_ns = now_ns();
        const int64_t t_strategy_triggered_ns = now_ns();
        const Side side = next_side();
        const double price = next_price(depth, side);
        const int64_t t_order_constructed_ns = now_ns();

        const uint64_t order_id = context->insert_order(
            symbol_,
            InstrumentType::Spot,
            exchange_,
            account_,
            price,
            qty_,
            OrderType::Limit,
            side);
        if (order_id == 0)
        {
            SPDLOG_ERROR("benchmark cpp insert_order failed symbol={} side={}", symbol_, side_name(side));
            return;
        }

        ++orders_;
        trace_->write_row(
            run_id_,
            "godzilla",
            static_cast<int64_t>(depth.data_time),
            symbol_,
            side_name(side),
            order_id,
            "gz-" + std::to_string(order_id),
            std::string(),
            std::string(),
            t_strategy_visible_ns,
            t_strategy_triggered_ns,
            t_order_constructed_ns);
    }

private:
    Side next_side()
    {
        if (!alternate_side_)
        {
            return Side::Buy;
        }
        return (orders_ % 2 == 0) ? Side::Buy : Side::Sell;
    }

    double next_price(const msg::data::Depth &depth, Side side) const
    {
        const double best_bid = depth.bid_price[0];
        const double best_ask = depth.ask_price[0];
        if (side == Side::Buy)
        {
            return best_bid > 0.0 ? best_bid : best_ask;
        }
        return best_ask > 0.0 ? best_ask : best_bid;
    }

private:
    yijinjing::data::location_ptr home_;
    std::string symbol_;
    std::string source_;
    std::string exchange_;
    std::string account_;
    std::string run_id_;
    std::string trace_mode_;
    std::string trace_path_;
    double qty_;
    int max_orders_;
    bool alternate_side_;
    int64_t orders_ = 0;
    std::unique_ptr<TraceWriter> trace_;
};

PYBIND11_MODULE(benchmark_cpp, m)
{
    py::class_<BenchmarkStrategy, Strategy, std::shared_ptr<BenchmarkStrategy>>(m, "Strategy")
        .def(py::init<yijinjing::data::location_ptr>())
        .def("pre_start", &BenchmarkStrategy::pre_start)
        .def("post_start", &BenchmarkStrategy::post_start)
        .def("pre_stop", &BenchmarkStrategy::pre_stop)
        .def("post_stop", &BenchmarkStrategy::post_stop)
        .def("on_depth", &BenchmarkStrategy::on_depth)
        .def("on_ticker", &BenchmarkStrategy::on_ticker)
        .def("on_transaction", &BenchmarkStrategy::on_transaction)
        .def("on_order", &BenchmarkStrategy::on_order)
        .def("on_trade", &BenchmarkStrategy::on_trade);
}
