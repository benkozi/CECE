// SPDX-License-Identifier: Apache-2.0
// CECE — Chemical Emissions Coupling Engine
// Copyright (c) HELM Project Contributors

/**
 * @file test_grid_spec_block.cpp
 * @brief GridSpec::from_esmf_block (one PET's DE block of a multi-tile parent grid, with explicit
 * corners) and the block destination mesh the regridder builds from it.
 *
 * The host-block path exists so a cubed-sphere tile block keeps the parent grid's true cell corners
 * at tile edges and DE seams instead of corners synthesized from centres. These tests pin:
 *   - the shape contract (centres nx*ny, corners (nx+1)*(ny+1), 1-based tile/origin), with named
 *     rejections for an open corner ring, mismatched arrays and bad indices;
 *   - longitude normalization of centres AND corners (ESMF holds [0, 360));
 *   - validate() and describe() on a host block;
 *   - build_block_mesh_with_corners: one node per corner, placed exactly where the corners are, and
 *     identical node coordinates to the synthesized-corner mesh when fed the midpoint corners of a
 *     uniform grid (ties the new path to the old one on the geometry they share).
 */
#include <gtest/gtest.h>

#include <Kokkos_Core.hpp>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#include "cece/cece_regridder_utils.hpp"
#include "cece/cece_simulation.hpp"

namespace {

struct Block {
    int nx = 4;
    int ny = 3;
    std::vector<double> lon, lat, klon, klat;  // centres (nx*ny) and corners ((nx+1)*(ny+1)), x fastest
};

/// A uniform 10-degree block whose first corner is at (lon0, lat0); centres in the same convention.
Block make_block(double lon0, double lat0, int nx = 4, int ny = 3) {
    Block b;
    b.nx = nx;
    b.ny = ny;
    for (int j = 0; j < ny; ++j) {
        for (int i = 0; i < nx; ++i) {
            b.lon.push_back(lon0 + 10.0 * i + 5.0);
            b.lat.push_back(lat0 + 10.0 * j + 5.0);
        }
    }
    for (int j = 0; j <= ny; ++j) {
        for (int i = 0; i <= nx; ++i) {
            b.klon.push_back(lon0 + 10.0 * i);
            b.klat.push_back(lat0 + 10.0 * j);
        }
    }
    return b;
}

}  // namespace

TEST(GridSpecBlock, AcceptsClosedCornerRingAndNormalizesLongitudes) {
    const Block b = make_block(300.0, -10.0);
    const cece::GridSpec spec = cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, b.lon, b.lat, b.klon, b.klat, 3, 1, 25);
    EXPECT_TRUE(spec.host_block);
    EXPECT_EQ(spec.topology, cece::GridTopology::Curvilinear);
    EXPECT_EQ(spec.tile, 3);
    EXPECT_EQ(spec.origin_i, 1);
    EXPECT_EQ(spec.origin_j, 25);
    ASSERT_EQ(spec.lon_coords.size(), 12u);
    ASSERT_EQ(spec.corner_lon_coords.size(), 20u);
    // 305 -> -55, 340 -> -20: both arrays wrapped into [-180, 180).
    EXPECT_DOUBLE_EQ(spec.lon_coords[0], -55.0);
    EXPECT_DOUBLE_EQ(spec.corner_lon_coords[4], -20.0);
    EXPECT_DOUBLE_EQ(spec.corner_lat_coords[19], 20.0);
    EXPECT_NO_THROW(spec.validate());
    EXPECT_NE(spec.describe().find("host block, tile 3 at 1,25"), std::string::npos);
}

TEST(GridSpecBlock, RejectsOpenCornerRing) {
    Block b = make_block(0.0, 0.0);
    b.klon.resize(static_cast<size_t>(b.nx + 1) * b.ny);  // the upper corner row is missing
    b.klat.resize(static_cast<size_t>(b.nx + 1) * b.ny);
    EXPECT_THROW(cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, b.lon, b.lat, b.klon, b.klat, 1, 1, 1), std::invalid_argument);
}

TEST(GridSpecBlock, RejectsBadShapesAndIndices) {
    const Block b = make_block(0.0, 0.0);
    std::vector<double> short_lon(b.lon.begin(), b.lon.end() - 1);
    EXPECT_THROW(cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, short_lon, b.lat, b.klon, b.klat, 1, 1, 1), std::invalid_argument);
    EXPECT_THROW(cece::GridSpec::from_esmf_block(b.nx, b.ny, 0, false, b.lon, b.lat, b.klon, b.klat, 1, 1, 1), std::invalid_argument);
    EXPECT_THROW(cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, b.lon, b.lat, b.klon, b.klat, 0, 1, 1), std::invalid_argument);
    EXPECT_THROW(cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, b.lon, b.lat, b.klon, b.klat, 1, 0, 1), std::invalid_argument);
}

TEST(GridSpecBlock, ValidateRequiresCornersOnHostBlockAndPairedCorners) {
    const Block b = make_block(0.0, 0.0);
    cece::GridSpec spec = cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, false, b.lon, b.lat, b.klon, b.klat, 1, 1, 1);
    spec.corner_lon_coords.clear();
    spec.corner_lat_coords.clear();
    EXPECT_THROW(spec.validate(), std::invalid_argument);
    cece::GridSpec plain = cece::GridSpec::from_esmf(b.nx, b.ny, 1, false, b.lon, b.lat);
    plain.corner_lon_coords = b.klon;  // lat corners missing
    EXPECT_THROW(plain.validate(), std::invalid_argument);
    plain.corner_lat_coords = b.klat;
    EXPECT_NO_THROW(plain.validate());
}

TEST(GridSpecBlock, RadiansAreConvertedForCentresAndCorners) {
    Block b = make_block(0.0, 0.0);
    const double d2r = M_PI / 180.0;
    for (double& v : b.lon) v *= d2r;
    for (double& v : b.lat) v *= d2r;
    for (double& v : b.klon) v *= d2r;
    for (double& v : b.klat) v *= d2r;
    const cece::GridSpec spec = cece::GridSpec::from_esmf_block(b.nx, b.ny, 1, true, b.lon, b.lat, b.klon, b.klat, 1, 1, 1);
    EXPECT_NEAR(spec.lon_coords[0], 5.0, 1e-12);
    EXPECT_NEAR(spec.corner_lat_coords[19], 30.0, 1e-12);
}

TEST(BlockMesh, NodesAreExactlyTheGivenCorners) {
    const Block b = make_block(-60.0, -15.0);
    auto mesh = cece::io::build_block_mesh_with_corners(b.nx, b.ny, b.lon, b.lat, b.klon, b.klat);
    ASSERT_EQ(mesh.n_cells(), static_cast<size_t>(b.nx) * b.ny);
    ASSERT_EQ(mesh.n_nodes(), static_cast<size_t>(b.nx + 1) * (b.ny + 1));
    const auto nodes = mesh.node_coords();
    for (size_t k = 0; k < mesh.n_nodes(); ++k) {
        EXPECT_DOUBLE_EQ(nodes(k, 0), b.klon[k]) << "node " << k;
        EXPECT_DOUBLE_EQ(nodes(k, 1), b.klat[k]) << "node " << k;
    }
}

TEST(BlockMesh, MatchesSynthesizedCornersOnAUniformGrid) {
    // On a uniform grid the midpoint corners the old path synthesizes ARE the explicit corners, so the
    // two meshes must coincide node for node; any disagreement means the corner layout convention
    // (x fastest, (nx+1)*(ny+1)) drifted between the two builders.
    const Block b = make_block(-60.0, -15.0);
    auto explicit_mesh = cece::io::build_block_mesh_with_corners(b.nx, b.ny, b.lon, b.lat, b.klon, b.klat);
    auto synthesized = cece::io::build_axis_mesh(b.nx, b.ny, b.lon, b.lat);
    ASSERT_EQ(explicit_mesh.n_nodes(), synthesized.n_nodes());
    const auto a = explicit_mesh.node_coords();
    const auto s = synthesized.node_coords();
    for (size_t k = 0; k < explicit_mesh.n_nodes(); ++k) {
        EXPECT_NEAR(a(k, 0), s(k, 0), 1e-9) << "lon of node " << k;
        EXPECT_NEAR(a(k, 1), s(k, 1), 1e-9) << "lat of node " << k;
    }
}

TEST(BlockMesh, RejectsMismatchedCornerCount) {
    Block b = make_block(0.0, 0.0);
    b.klon.pop_back();
    EXPECT_THROW(cece::io::build_block_mesh_with_corners(b.nx, b.ny, b.lon, b.lat, b.klon, b.klat), std::invalid_argument);
}
