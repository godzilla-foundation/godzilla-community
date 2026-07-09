//
// Created by kx@godzilla.dev on 2026-07-09.
//

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

class DemoStrategy : public Strategy
{
public:
    DemoStrategy(yijinjing::data::location_ptr home)
    {
        yijinjing::log::copy_log_settings(home, "demo");
    };

    void pre_start(Context_ptr context) override
    {
        context->subscribe("xtc", {"btc_usdt"}, InstrumentType::Spot, "xt");
        context->add_account("xtc", "xt_user1");
        SPDLOG_INFO("cpp demo pre start");
    };

    void on_depth(Context_ptr context, const msg::data::Depth &depth) override
    {
        SPDLOG_INFO("cpp demo on depth");
    };

    void on_trade(Context_ptr context, const msg::data::Trade &trade) override
    {
        SPDLOG_INFO("cpp demo on trade");
    };
};

PYBIND11_MODULE(demo_cpp, m)
{
    py::class_<DemoStrategy, Strategy, std::shared_ptr<DemoStrategy>>(m, "Strategy")
        .def(py::init<yijinjing::data::location_ptr>())
        .def("pre_start", &DemoStrategy::pre_start)
        .def("post_start", &DemoStrategy::post_start)
        .def("pre_stop", &DemoStrategy::pre_stop)
        .def("post_stop", &DemoStrategy::post_stop)
        .def("on_depth", &DemoStrategy::on_depth)
        .def("on_ticker", &DemoStrategy::on_ticker)
        .def("on_transaction", &DemoStrategy::on_transaction)
        .def("on_order", &DemoStrategy::on_order)
        .def("on_trade", &DemoStrategy::on_trade);
}
