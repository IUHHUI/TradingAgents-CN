#!/usr/bin/env python3
"""
FIU数据源测试用例
测试 data_fetchers/data_sources/fiu_source.py 中的各个数据源类
"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__)))

import unittest
import pandas as pd
import logging
import os

from fiu_source import (
    FiuPriceDataSource,
    FiuFundamentalDataSource,
)

# 设置测试日志级别
logging.basicConfig(level=logging.WARNING)


class TestFiuPriceDataSource(unittest.TestCase):
    """FIU价格数据源测试"""

    def setUp(self):
        """测试前准备"""
        self.api_tokens = {}
        self.price_source = FiuPriceDataSource(self.api_tokens)

    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.price_source.name, "FIU")
        self.assertIn("hk_stock", self.price_source.endpoints)
        self.assertIn("us_stock", self.price_source.endpoints)
        self.assertIn("a_stock", self.price_source.endpoints)

    def test_parse_period(self):
        """测试周期参数解析"""
        test_cases = [
            ("1d", (0, 1)),
            ("1w", (1, 1)),
            ("1m", (2, 1)),
            ("3m", (0, 66)),
            ("6m", (0, 132)),
            ("1y", (0, 250)),
            ("2y", (0, 500)),
            ("5y", (0, 1250)),
            ("1min", (5, 240)),
            ("5min", (6, 288)),
            ("15min", (7, 96)),
            ("30min", (8, 48)),
            ("1h", (9, 24)),
            ("invalid", (0, 250)),  # 默认值
        ]

        for period, expected in test_cases:
            result = self.price_source._parse_period(period)
            self.assertEqual(
                result, expected, f"Period {period} should return {expected}"
            )

    def test_get_kline_url(self):
        """测试K线URL获取"""
        url_tests = [
            ("hk_stock", "https://mdci.szfiu.com/h5/stock/hk/ss/v1/chart/kline/list"),
            (
                "us_stock",
                "https://mdci.szfiu.com/h5/stock/us/nasdq/v1/chart/kline/list",
            ),
            ("a_stock", "https://mdci.szfiu.com/h5/stock/hs/lv1/v1/chart/kline/list"),
            ("us_otc", "https://mdcc.szfiu.com/api/stock/us/otc/v1/kline/list"),
            ("jp_stock", "https://mdci.szfiu.com/h5/stock/jp/v1/chart/kline/list"),
            ("invalid_market", None),
        ]

        for market, expected_url in url_tests:
            result = self.price_source._get_kline_url(market)
            self.assertEqual(
                result, expected_url, f"Market {market} should return {expected_url}"
            )

    def test_get_kline_headers(self):
        """测试K线请求头"""
        # 测试标准市场
        headers = self.price_source._get_kline_headers("hk_stock")
        self.assertEqual(headers["Content-Type"], "application/json")

        # 测试OTC市场
        otc_headers = self.price_source._get_kline_headers("us_otc")
        self.assertNotIn("Org-Date-Enable", otc_headers)

        # 测试无效市场
        empty_headers = self.price_source._get_kline_headers("invalid")
        self.assertEqual(empty_headers, {})

    def test_build_kline_payload(self):
        """测试K线请求payload构建"""
        # 测试标准市场payload
        payload = self.price_source._build_kline_payload("000001.sz", "a_stock", 0, 250)
        expected_keys = [
            "candleMode",
            "date",
            "number",
            "orderMode",
            "symbol",
            "timeMode",
            "type",
        ]
        for key in expected_keys:
            self.assertIn(key, payload)

        self.assertEqual(payload["symbol"], "000001.sz")
        self.assertEqual(payload["type"], 0)
        self.assertEqual(payload["number"], 250)

        # 测试OTC市场payload
        otc_payload = self.price_source._build_kline_payload(
            "AAPL.us", "us_otc", 0, 100
        )
        otc_keys = ["timeMode", "date", "number", "symbol", "type"]
        for key in otc_keys:
            self.assertIn(key, otc_payload)

        self.assertEqual(otc_payload["symbol"], "AAPL")  # 应该去掉.us后缀

    def test_get_stock_data_success(self):
        """测试成功获取股票数据"""
        # 测试获取数据 - 实际调用函数
        print("\n=== 测试A股数据 ===")
        result = self.price_source.get_stock_data("000001.sz", "a_stock", "1y")
        print(f"A股 000001.sz 数据类型: {type(result)}")
        if isinstance(result, pd.DataFrame):
            print(f"数据形状: {result.shape}")
            print(f"列名: {list(result.columns)}")
            print(f"最近5行数据:\n{result.tail()}")
        else:
            print(f"返回结果: {result}")
        self.assertTrue(isinstance(result, pd.DataFrame))

        print("\n=== 测试港股数据 ===")
        result = self.price_source.get_stock_data("00700.hk", "hk_stock", "1y")
        print(f"港股 00700.hk 数据类型: {type(result)}")
        if isinstance(result, pd.DataFrame):
            print(f"数据形状: {result.shape}")
            print(f"最近5行数据:\n{result.tail()}")
        else:
            print(f"返回结果: {result}")
        self.assertTrue(isinstance(result, pd.DataFrame))

        print("\n=== 测试美股数据 ===")
        result = self.price_source.get_stock_data("AAPL.us", "us_stock", "1y")
        print(f"美股 AAPL.us 数据类型: {type(result)}")
        if isinstance(result, pd.DataFrame):
            print(f"数据形状: {result.shape}")
            print(f"最近5行数据:\n{result.tail()}")
        else:
            print(f"返回结果: {result}")
        self.assertTrue(isinstance(result, pd.DataFrame))

        print("\n=== 测试日股数据 ===")
        result = self.price_source.get_stock_data("6059.jp", "jp_stock", "1y")
        print(f"日股 6059.jp 数据类型: {type(result)}")
        if isinstance(result, pd.DataFrame):
            print(f"数据形状: {result.shape}")
            print(f"最近5行数据:\n{result.tail()}")
        else:
            print(f"返回结果: {result}")
        self.assertTrue(isinstance(result, pd.DataFrame))

        print("\n=== 测试美股OTC数据 ===")
        result = self.price_source.get_stock_data("DIDIY.us", "us_otc", "1y")
        print(f"美股OTC DIDIY.us 数据类型: {type(result)}")
        if isinstance(result, pd.DataFrame):
            print(f"数据形状: {result.shape}")
            print(f"最近5行数据:\n{result.tail()}")
        else:
            print(f"返回结果: {result}")
        self.assertTrue(isinstance(result, pd.DataFrame))

    def test_get_stock_data_failure(self):
        """测试获取股票数据失败"""
        # 使用无效的股票代码测试失败情况
        result = self.price_source.get_stock_data("INVALID", "invalid_market", "1y")
        self.assertIsNone(result)

    def test_format_kline_dataframe(self):
        """测试K线数据格式化"""
        mock_data = []

        result = self.price_source._format_kline_dataframe(mock_data, "a_stock")

        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


class TestFiuFundamentalDataSource(unittest.TestCase):
    """FIU基本面数据源测试"""

    def setUp(self):
        """测试前准备"""
        self.api_tokens = {}
        self.fundamental_source = FiuFundamentalDataSource(self.api_tokens)

    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.fundamental_source.name, "FIU")

    def test_init_with_env_vars(self):
        """测试使用环境变量初始化"""
        # 设置环境变量
        old_bearer = os.environ.get("FIU_BEARER_TOKEN")

        os.environ["FIU_BEARER_TOKEN"] = "test_bearer"

        try:
            source = FiuFundamentalDataSource()
            self.assertEqual(source.api_tokens["bearer_token"], "test_bearer")
        finally:
            # 恢复环境变量
            if old_bearer is not None:
                os.environ["FIU_BEARER_TOKEN"] = old_bearer
            elif "FIU_BEARER_TOKEN" in os.environ:
                del os.environ["FIU_BEARER_TOKEN"]

    def test_get_financial_headers(self):
        """测试财务数据请求头"""
        headers = self.fundamental_source._get_financial_headers()

        required_headers = [
            "Authorization",
            "Content-Type",
            "Accept",
        ]
        for header in required_headers:
            self.assertIn(header, headers)

        self.assertTrue(headers["Authorization"].startswith("Bearer"))
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_format_income_data(self):
        """测试利润表数据格式化"""
        raw_data = {}

        result = self.fundamental_source._format_income_data(raw_data)

        self.assertIsInstance(result, dict)

    def test_format_balance_data(self):
        """测试资产负债表数据格式化"""
        raw_data = {}

        result = self.fundamental_source._format_balance_data(raw_data)

        self.assertIsInstance(result, dict)

    def test_format_cash_flow_data(self):
        """测试现金流量表数据格式化"""
        raw_data = {}

        result = self.fundamental_source._format_cash_flow_data(raw_data)

        self.assertIsInstance(result, dict)

    def test_get_financial_indicators_success(self):
        """测试成功获取财务指标"""
        # 实际调用函数测试
        print("\n=== 测试财务指标数据 ===")
        result = self.fundamental_source.get_financial_indicators(
            "000001.sz", "a_stock"
        )
        print(f"财务指标数据类型: {type(result)}")
        print(f"返回结果: {result}")
        self.assertIsInstance(result, dict)

        result = self.fundamental_source.get_financial_indicators(
            "00700.hk", "hk_stock"
        )
        print(f"财务指标数据类型: {type(result)}")
        print(f"返回结果: {result}")
        self.assertIsInstance(result, dict)

        result = self.fundamental_source.get_financial_indicators("AAPL.us", "us_stock")
        print(f"财务指标数据类型: {type(result)}")
        print(f"返回结果: {result}")
        self.assertIsInstance(result, dict)

    def test_get_financial_indicators_failure(self):
        """测试获取财务指标失败"""
        # 使用无效参数测试失败情况
        result = self.fundamental_source.get_financial_indicators(
            "INVALID", "invalid_market"
        )
        self.assertEqual(result, {})

    def test_get_financial_indicators_invalid_market(self):
        """测试无效市场类型"""
        result = self.fundamental_source.get_financial_indicators(
            "000001.sz", "invalid_market"
        )
        self.assertEqual(result, {})

    def test_get_income_statement(self):
        """测试获取利润表"""
        # 实际调用函数测试
        result = self.fundamental_source._get_income_statement(
            "000001.sz", "a_stock", "2024-01-01", "2025-12-31"
        )

        self.assertIsInstance(result, dict)

    def test_get_major_shareholders_url(self):
        """测试获取主要股东URL"""
        test_cases = [
            ("hk_stock", "https://globaldata1-ali.szfuit.com/api/hk/f10/summary/major-shareholders"),
            ("us_stock", "https://globaldata1-ali.szfuit.com/api/us/f10/summary/major-shareholders"),
            ("a_stock", "https://globaldata1-ali.szfuit.com/api/hs/f10/summary/topten-holder-stastatistics"),
            ("invalid_market", None),
        ]
        
        for market, expected_url in test_cases:
            result = self.fundamental_source._get_major_shareholders_url(market)
            self.assertEqual(
                result, expected_url, f"Market {market} should return {expected_url}"
            )

    def test_build_major_shareholders_payload(self):
        """测试构建主要股东请求payload"""
        # 测试港股和美股payload
        for market in ["hk_stock", "us_stock"]:
            payload = self.fundamental_source._build_major_shareholders_payload(
                "00700.hk", market
            )
            expected_keys = ["symbol", "sort"]
            for key in expected_keys:
                self.assertIn(key, payload)
            self.assertEqual(payload["symbol"], "00700.hk")
            self.assertEqual(payload["sort"], "desc")
        
        # 测试A股payload
        payload = self.fundamental_source._build_major_shareholders_payload(
            "600519.sh", "a_stock"
        )
        expected_keys = ["symbol", "sort"]
        for key in expected_keys:
            self.assertIn(key, payload)
        self.assertEqual(payload["symbol"], "600519.sh")
        self.assertEqual(payload["sort"], "desc")
        
        # 测试无效市场
        empty_payload = self.fundamental_source._build_major_shareholders_payload(
            "TEST", "invalid_market"
        )
        self.assertEqual(empty_payload, {})

    def test_format_major_shareholders_hk(self):
        """测试港股主要股东数据格式化"""
        mock_hk_data = [
            {
                "symbol": "00700.HK",
                "holderName": "Prosus N.V.",
                "holderNameEn": "Prosus N.V.",
                "holderType": "法团",
                "holdingNumber": 2105253100,
                "holdingRatio": 22.95600,
                "changeNumber": None,
                "reportDate": "2025-07-25",
                "dataSource": "权益披露",
                "holderSeccode": None,
            }
        ]
        
        result = self.fundamental_source._format_major_shareholders(mock_hk_data, "hk_stock")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        
        shareholder = result[0]
        self.assertEqual(shareholder["symbol"], "00700.HK")
        self.assertEqual(shareholder["holder_name"], "Prosus N.V.")
        self.assertEqual(shareholder["holder_name_en"], "Prosus N.V.")
        self.assertEqual(shareholder["holder_type"], "法团")
        self.assertEqual(shareholder["holding_number"], 2105253100)
        self.assertEqual(shareholder["holding_ratio"], 22.95600)
        self.assertEqual(shareholder["report_date"], "2025-07-25")
        self.assertEqual(shareholder["data_source"], "权益披露")
        # changeNumber和holderSeccode为None，应该被过滤掉
        self.assertNotIn("change_number", shareholder)
        self.assertNotIn("holder_seccode", shareholder)

    def test_format_major_shareholders_us(self):
        """测试美股主要股东数据格式化"""
        mock_us_data = [
            {
                "symbol": "AAPL.US",
                "holderName": "The Vanguard Group, Inc.",
                "holderType": "B",
                "holdingRatio": 8.85574115,
                "holdingNumber_ADS": 1.3303159E9,
                "holdingNumber_OS": 1.3303159E9,
                "changeNumber_ADS": 2952904.0,
                "changeNumber_OS": 2952904.0,
                "changeRatio_ADS": 0.2224639385683161,
                "changeRatio_OS": 0.2224639385683161,
                "reportDate": "2025-03-31",
                "pubDate": "2025-07-23",
            }
        ]
        
        result = self.fundamental_source._format_major_shareholders(mock_us_data, "us_stock")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        
        shareholder = result[0]
        self.assertEqual(shareholder["symbol"], "AAPL.US")
        self.assertEqual(shareholder["holder_name"], "The Vanguard Group, Inc.")
        self.assertEqual(shareholder["holder_type"], "B")
        self.assertEqual(shareholder["holding_ratio"], 8.85574115)
        self.assertEqual(shareholder["holding_number_ads"], 1.3303159E9)
        self.assertEqual(shareholder["holding_number_os"], 1.3303159E9)
        self.assertEqual(shareholder["report_date"], "2025-03-31")
        self.assertEqual(shareholder["pub_date"], "2025-07-23")

    def test_format_major_shareholders_a_stock(self):
        """测试A股主要股东数据格式化"""
        mock_a_data = [
            {
                "symbol": "600519.SH",
                "holderName": "中国贵州茅台酒厂(集团)有限责任公司",
                "holdingRatio": 54.0700,
                "holdingNumber": 679211576.0000,
                "holdingRatioChange": 0.0000,
                "holdingNumberChange": 0.0000,
                "reportDate": "2025-06-30",
                "type": 10
            }
        ]
        
        result = self.fundamental_source._format_major_shareholders(mock_a_data, "a_stock")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        
        shareholder = result[0]
        self.assertEqual(shareholder["symbol"], "600519.SH")
        self.assertEqual(shareholder["holder_name"], "中国贵州茅台酒厂(集团)有限责任公司")
        self.assertEqual(shareholder["holder_type"], 10)
        self.assertEqual(shareholder["holding_ratio"], 54.0700)
        self.assertEqual(shareholder["holding_number"], 679211576.0000)
        self.assertEqual(shareholder["holding_number_change"], 0.0000)
        self.assertEqual(shareholder["holding_ratio_change"], 0.0000)
        self.assertEqual(shareholder["report_date"], "2025-06-30")

    def test_get_major_shareholders_success(self):
        """测试成功获取主要股东数据"""
        print("\n=== 测试主要股东数据 ===")
        
        # 测试港股主要股东数据
        print("\n--- 港股主要股东数据 ---")
        result = self.fundamental_source.get_major_shareholders("00700.hk", "hk_stock")
        print(f"港股 00700.hk 主要股东数据类型: {type(result)}")
        print(f"数据长度: {len(result) if isinstance(result, list) else 'N/A'}")
        if isinstance(result, list) and len(result) > 0:
            print(f"第一个股东数据: {result[0]}")
        else:
            print(f"返回结果: {result}")
        self.assertIsInstance(result, list)
        
        # 测试美股主要股东数据
        print("\n--- 美股主要股东数据 ---")
        result = self.fundamental_source.get_major_shareholders("AAPL.us", "us_stock")
        print(f"美股 AAPL.us 主要股东数据类型: {type(result)}")
        print(f"数据长度: {len(result) if isinstance(result, list) else 'N/A'}")
        if isinstance(result, list) and len(result) > 0:
            print(f"第一个股东数据: {result[0]}")
        else:
            print(f"返回结果: {result}")
        self.assertIsInstance(result, list)
        
        # 测试A股主要股东数据
        print("\n--- A股主要股东数据 ---")
        result = self.fundamental_source.get_major_shareholders("600519.sh", "a_stock")
        print(f"A股 600519.sh 主要股东数据类型: {type(result)}")
        print(f"数据长度: {len(result) if isinstance(result, list) else 'N/A'}")
        if isinstance(result, list) and len(result) > 0:
            print(f"第一个股东数据: {result[0]}")
        else:
            print(f"返回结果: {result}")
        self.assertIsInstance(result, list)

    def test_get_major_shareholders_failure(self):
        """测试获取主要股东数据失败"""
        # 使用无效参数测试失败情况
        result = self.fundamental_source.get_major_shareholders(
            "INVALID", "invalid_market"
        )
        self.assertEqual(result, [])
        
        # 测试无效股票代码
        result = self.fundamental_source.get_major_shareholders(
            "INVALID_CODE", "hk_stock"
        )
        self.assertIsInstance(result, list)


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_all_sources_initialization(self):
        """测试所有数据源可以正常初始化"""
        api_tokens = {}

        # 测试价格数据源
        price_source = FiuPriceDataSource(api_tokens)
        self.assertIsNotNone(price_source)
        self.assertEqual(price_source.name, "FIU")

        # 测试基本面数据源
        fundamental_source = FiuFundamentalDataSource(api_tokens)
        self.assertIsNotNone(fundamental_source)
        self.assertEqual(fundamental_source.name, "FIU")

    def test_market_support(self):
        """测试市场支持"""
        supported_markets = ["a_stock", "hk_stock", "us_stock"]

        price_source = FiuPriceDataSource()
        for market in supported_markets:
            # 测试URL生成
            url = price_source._get_kline_url(market)
            self.assertIsNotNone(url, f"Market {market} should have a URL")

            # 测试请求头生成
            headers = price_source._get_kline_headers(market)
            self.assertIsInstance(headers, dict, f"Market {market} should have headers")

        fundamental_source = FiuFundamentalDataSource()
        for market in supported_markets:
            for statement_type in ["income", "balance", "cash"]:
                url = fundamental_source._get_financial_url(market, statement_type)
                self.assertIsNotNone(
                    url, f"Market {market} statement {statement_type} should have URL"
                )
            
            # 测试主要股东数据URL
            shareholders_url = fundamental_source._get_major_shareholders_url(market)
            self.assertIsNotNone(
                shareholders_url, f"Market {market} should have major shareholders URL"
            )


if __name__ == "__main__":
    # 创建测试套件
    test_suite = unittest.TestSuite()

    # 添加测试用例
    test_classes = [
        TestFiuPriceDataSource,
        TestFiuFundamentalDataSource,
        TestIntegration,
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # 输出测试结果统计
    print(f"\n{'='*60}")
    print(f"测试结果统计:")
    print(f"总测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print(f"跳过: {len(result.skipped) if hasattr(result, 'skipped') else 0}")

    if result.failures:
        print(f"\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}")

    if result.errors:
        print(f"\n错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}")

    # 返回退出码
    sys.exit(0 if result.wasSuccessful() else 1)
