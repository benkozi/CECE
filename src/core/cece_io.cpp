#include "cece/cece_io.hpp"

#include <yaml-cpp/yaml.h>

#include <fstream>
#include <stdexcept>

namespace cece {
namespace io {

void CeceIO::Initialize(const std::string& config_file, int nx, int ny, int nz) {
    std::ifstream f(config_file);
    if (!f.good()) {
        throw std::runtime_error("File not found: " + config_file);
    }

    YAML::Node config = YAML::LoadFile(config_file);
    nx_ = nx;
    ny_ = ny;
    nz_ = nz;

    if (config["cece_data"] && config["cece_data"]["streams"]) {
        for (const auto& stream : config["cece_data"]["streams"]) {
            for (const auto& var : stream["variables"]) {
                std::string var_name = var["model"].as<std::string>();
                var_names_.push_back(var_name);

                DeviceView view(var_name, nx_, ny_, nz_);
                Kokkos::deep_copy(view, 0.0);
                field_views_[var_name] = view;
            }
        }
    }
}

Kokkos::View<double***, Kokkos::LayoutLeft, Kokkos::DefaultExecutionSpace> CeceIO::GetFieldView(const std::string& name) {
    return field_views_.at(name);
}

void CeceIO::Finalize() {
    field_views_.clear();
    var_names_.clear();
}

}  // namespace io
}  // namespace cece
