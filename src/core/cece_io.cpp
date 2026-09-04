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
                std::string var_name;
                int field_levels = nz_;
                if (var.IsScalar()) {
                    var_name = var.as<std::string>();
                } else if (var.IsMap() && var["model"]) {
                    var_name = var["model"].as<std::string>();
                    if (var["levels"]) field_levels = var["levels"].as<int>();
                } else {
                    throw std::runtime_error("cece_data variable must be a scalar name or a map containing 'model'");
                }
                if (field_levels < 1) {
                    throw std::runtime_error("cece_data variable '" + var_name + "' has invalid levels=" + std::to_string(field_levels));
                }

                var_names_.push_back(var_name);

                DeviceView view(var_name, nx_, ny_, field_levels);
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
