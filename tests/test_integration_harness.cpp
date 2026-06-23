#include <gtest/gtest.h>
#include <vector>
#include <string>
#include <memory>
#include <stdexcept>

namespace cece::test {

class DataRetriever {
public:
    virtual ~DataRetriever() = default;
    virtual std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) = 0;
};

class MockDataRetriever : public DataRetriever {
public:
    std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) override {
        std::vector<double> data(nx * ny * nz, 0.0);
        for (int k = 0; k < nz; ++k) {
            for (int j = 0; j < ny; ++j) {
                for (int i = 0; i < nx; ++i) {
                    double lon = lons[i];
                    double lat = lats[j];
                    int idx = k * (nx * ny) + j * nx + i;
                    data[idx] = lat + lon + static_cast<double>(step);
                }
            }
        }
        return data;
    }
};

class NetCDFDataRetriever : public DataRetriever {
public:
    std::vector<double> RetrieveField(
        const std::string& name,
        int step,
        int nx, int ny, int nz,
        const std::vector<double>& lons,
        const std::vector<double>& lats
    ) override {
        throw std::runtime_error("NetCDF file reading is not supported/implemented in this milestone.");
    }
};

} // namespace cece::test

TEST(DataRetrieverTest, MockDataGeneratorValues) {
    cece::test::MockDataRetriever retriever;
    std::vector<double> lons = {-180.0, -90.0, 0.0, 90.0};
    std::vector<double> lats = {-90.0, -30.0, 30.0, 90.0};
    int nx = 4, ny = 4, nz = 1;
    int step = 2;
    
    auto result = retriever.RetrieveField("co", step, nx, ny, nz, lons, lats);
    ASSERT_EQ(result.size(), 16);
    // Expected value at index 0: lats[0] + lons[0] + step = -90.0 + -180.0 + 2.0 = -268.0
    EXPECT_DOUBLE_EQ(result[0], -268.0);
}

TEST(DataRetrieverTest, NetCDFRetrieverThrows) {
    cece::test::NetCDFDataRetriever retriever;
    EXPECT_THROW(retriever.RetrieveField("co", 1, 4, 4, 1, {}, {}), std::runtime_error);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
