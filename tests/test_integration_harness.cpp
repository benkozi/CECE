#include <gtest/gtest.h>

TEST(IntegrationHarnessTest, FailOnPurpose) {
    ASSERT_TRUE(false) << "Scaffolding fail verification";
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
