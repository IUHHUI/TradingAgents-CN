"""
FIU Data Source Implementation
FIU数据源实现 - 基于FIU数据API的数据源
"""

import logging
import pandas as pd
import requests
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    from .base import BasePriceDataSource, BaseFundamentalDataSource
except ImportError:
    from base import BasePriceDataSource, BaseFundamentalDataSource


class FiuTokenManager:
    """FIU Token管理器 - 基于时间检查的简单token刷新"""

    def __init__(self, token_url: str):
        """
        初始化Token管理器

        Args:
            token_url: 获取token的URL
        """
        self.logger = logging.getLogger(__name__)
        self.token_url = token_url
        self._token = ""
        self._token_fiu_auth = ""
        self._token_lock = threading.Lock()
        self._last_refresh = None

        # 首次获取token
        self._fetch_token()

    def _fetch_token(self) -> bool:
        self._fetch_http_token()
        self._fetch_fiu_auth_token()
        return True

    def _fetch_http_token(self) -> bool:
        """
        从FIU_TOKEN_URL获取新的token

        Returns:
            bool: 是否成功获取token
        """
        try:
            self.logger.debug("正在获取FIU token...")

            response = requests.get(self.token_url, timeout=10)
            response.raise_for_status()

            token = response.content.decode("utf-8")
            if token:
                self._token = token
                self._last_refresh = datetime.now()
                self.logger.info(f"FIU token更新成功，时间: {self._last_refresh}")
                return True
            else:
                self.logger.error(f"无法从响应中提取token: {response}")
                return False

        except Exception as e:
            self.logger.error(f"获取FIU token失败: {str(e)}")
            return False

    def _fetch_fiu_auth_token(self) -> bool:
        auth_url = os.getenv("FIU_AUTH_URL", "")
        mobile = os.getenv("FIU_AUTH_MOBILE", "")
        verifycode = os.getenv("FIU_AUTH_VERIFY_CODE", "")

        if auth_url and mobile and verifycode:
            url = auth_url + "/oauth/token"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic Zml1OmZpdV9zZWNyZXQ",
                "Tenant-Id": "431500",
                "Dept-Code": "FIU",
            }
            # 构造表单数据（application/x-www-form-urlencoded）
            data = {
                "grant_type": "sms_code",
                "mobile": mobile,
                "id": "",
                "code": "DynamicCode",
                "value": verifycode,
            }

            try:
                response = requests.post(url, headers=headers, data=data)
                response.raise_for_status()  # 检查请求是否成功

                # 解析返回的 JSON 数据
                json_data = response.json()
                data_payload = json_data.get("data")
                if data_payload:
                    access_token = data_payload.get("access_token")
                    if access_token:
                        self._token_fiu_auth = access_token
                        return True
            except Exception as e:
                self.logger.error(f"获取FIU API令牌失败: {str(e)}")
        return False

    def get_token(self, fiu_auth: bool = False) -> str:
        """
        获取当前有效的token，如果超过50分钟则自动刷新

        Returns:
            str: 当前token
        """
        # 检查是否需要刷新token
        if self._should_refresh_token():
            self.logger.debug("Token已超过50分钟，开始自动刷新...")
            with self._token_lock:
                # 加锁, 避免同时刷新token
                if self._should_refresh_token():
                    self._fetch_token()

        return self._token_fiu_auth if fiu_auth else self._token

    def _should_refresh_token(self) -> bool:
        """
        检查是否应该刷新token（超过50分钟）

        Returns:
            bool: 是否应该刷新token
        """
        if not self._last_refresh:
            return True

        # 检查距离上次刷新是否超过50分钟
        elapsed = datetime.now() - self._last_refresh
        return elapsed.total_seconds() > 50 * 60  # 50分钟

    def is_token_valid(self) -> bool:
        """
        检查token是否仍然有效（未超过55分钟）

        Returns:
            bool: token是否有效
        """
        if not self._token or not self._last_refresh:
            return False

        # 检查token是否已过期（55分钟后认为过期，留5分钟缓冲）
        elapsed = datetime.now() - self._last_refresh
        return elapsed.total_seconds() < 55 * 60


# 全局token管理器实例
_token_manager = None
_token_manager_lock = threading.Lock()


def get_fiu_token_manager() -> Optional[FiuTokenManager]:
    """
    获取全局FIU token管理器实例

    Returns:
        FiuTokenManager: token管理器实例，如果未配置则返回None
    """
    global _token_manager

    if _token_manager is None:
        with _token_manager_lock:
            if _token_manager is None:
                import os

                token_url = os.getenv("FIU_TOKEN_URL")
                if token_url:
                    try:
                        _token_manager = FiuTokenManager(token_url)
                    except Exception as e:
                        logging.getLogger(__name__).error(
                            f"初始化FIU token管理器失败: {str(e)}"
                        )
                        return None

    return _token_manager


class FiuPriceDataSource(BasePriceDataSource):
    """FIU价格数据源"""

    def __init__(self, api_tokens: Optional[Dict[str, str]] = None):
        """初始化FIU价格数据源"""
        self.logger = logging.getLogger(__name__)
        self.name = "FIU"
        self._available = False

        # API endpoints for different markets
        self.endpoints = {
            "hk_stock": {
                "quote": "https://cms-hk-api-sdk.szfiu.com/v3/stock/quote",
                "extend": "https://cms-hk-api-sdk.szfiu.com/v3/stock/quote/extend",
                "index_quote": "https://cms-hk-api-sdk.szfiu.com/v3/index/quote",
            },
            "us_stock": {
                "quote": "https://cms-us-api-sdk.szfiu.com/v1/stock/quote",
                "extend": "https://cms-us-api-sdk.szfiu.com/v1/stock/quote/extend",
                "index_quote": "https://cms-us-api-sdk.szfiu.com/v1/index/quote",
            },
            "a_stock": {
                "quote": "https://cms-hs-api-sdk.szfiu.com/v1/stock/quote",
                "extend": "https://cms-hs-api-sdk.szfiu.com/v1/stock/quote/extend",
                "index_quote": "https://cms-hs-api-sdk.szfiu.com/v1/index/quote",
            },
            "us_otc": {
                "quote": "https://mdcc.szfiu.com/api/stock/us/otc/v1/snapshot",
                "extend": "https://mdcc.szfiu.com/api/stock/us/otc/v1/quote/extend",
            },
            "jp_stock": {
                "quote": "https://mdci.szfiu.com/h5/stock/jp/v1/quote/getSnapshotList",
                "extend": "https://mdci.szfiu.com/h5/stock/jp/v1/quote/extend",
            },
        }

        # 获取token管理器
        self._token_manager = get_fiu_token_manager()

        # 从配置或环境变量中获取API tokens，如果没有则使用空值
        import os

        self.api_tokens = api_tokens or {
            "bearer_token": os.getenv("FIU_BEARER_TOKEN", ""),
        }

    def _get_current_bearer_token(self, fiu_auth: bool = False) -> str:
        """
        获取当前有效的bearer token

        Returns:
            str: 当前有效的token
        """
        if self._token_manager:
            token = self._token_manager.get_token(fiu_auth=fiu_auth)
            if token:
                return token

        # 如果token管理器不可用，回退到环境变量
        return self.api_tokens.get("bearer_token", "")

    def get_stock_data(
        self, stock_code: str, market: str, period: str = "1y"
    ) -> Optional[pd.DataFrame]:
        """
        获取股票价格数据 (K线数据)

        Args:
            stock_code: 股票代码
            market: 市场类型 (a_stock, hk_stock, us_stock, us_otc, jp_stock)
            period: 时间周期 (1d, 1w, 1m, 3m, 6m, 1y, 2y, 5y)

        Returns:
            DataFrame: 价格数据，包含 ['date', 'open', 'high', 'low', 'close', 'volume'] 列
        """
        try:
            self.logger.debug(
                f"FIU获取K线数据: {stock_code}, 市场: {market}, 周期: {period}"
            )

            # 解析周期参数并获取数据条数
            kline_type, num_records = self._parse_period(period)

            # 获取K线数据
            kline_data = self._get_kline_data(
                stock_code, market, kline_type, num_records
            )
            if not kline_data:
                return None

            # 转换为DataFrame并标准化格式
            df = self._format_kline_dataframe(kline_data, market)
            return df

        except Exception as e:
            self.logger.error(
                f"获取K线数据失败: {stock_code}, {market}, {period}, 错误: {str(e)}"
            )
            return None

    def _parse_period(self, period: str) -> tuple[int, int]:
        """
        解析周期参数

        Args:
            period: 周期字符串 (如 '1d', '1w', '1m', '1y' 等)

        Returns:
            tuple: (kline_type, num_records)
        """
        period_map = {
            "1d": (0, 1),  # 日K, 1条
            "1w": (1, 1),  # 周K, 1条
            "1m": (2, 1),  # 月K, 1条
            "3m": (0, 66),  # 日K, 约3个月 (66个交易日)
            "6m": (0, 132),  # 日K, 约6个月 (132个交易日)
            "1y": (0, 250),  # 日K, 约1年 (250个交易日)
            "2y": (0, 500),  # 日K, 约2年
            "5y": (0, 1250),  # 日K, 约5年
            # 分钟级别
            "1min": (5, 240),  # 1分钟K, 4小时数据
            "5min": (6, 288),  # 5分钟K, 1天数据
            "15min": (7, 96),  # 15分钟K, 1天数据
            "30min": (8, 48),  # 30分钟K, 1天数据
            "1h": (9, 24),  # 1小时K, 1天数据
        }

        return period_map.get(period, (0, 250))  # 默认日K，1年数据

    def _get_kline_data(
        self, stock_code: str, market: str, kline_type: int, num_records: int
    ) -> Optional[List[Dict[str, Any]]]:
        """获取K线原始数据"""
        try:
            url = self._get_kline_url(market)
            if not url:
                self.logger.error(f"不支持的K线市场类型: {market}")
                return None

            headers = self._get_kline_headers(market)
            payload = self._build_kline_payload(
                stock_code, market, kline_type, num_records
            )

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_kline_response(data, market)

        except Exception as e:
            self.logger.error(f"获取K线原始数据失败: {str(e)}")
            return None

    def _get_kline_url(self, market: str) -> Optional[str]:
        """根据市场类型获取K线API端点"""
        kline_urls = {
            "hk_stock": "https://mdci.szfiu.com/h5/stock/hk/ss/v1/chart/kline/list",
            "us_stock": "https://mdci.szfiu.com/h5/stock/us/nasdq/v1/chart/kline/list",
            "a_stock": "https://mdci.szfiu.com/h5/stock/hs/lv1/v1/chart/kline/list",
            "us_otc": "https://mdcc.szfiu.com/api/stock/us/otc/v1/kline/list",
            "jp_stock": "https://mdci.szfiu.com/h5/stock/jp/v1/chart/kline/list",
        }
        return kline_urls.get(market)

    def _get_kline_headers(self, market: str) -> Dict[str, str]:
        """根据市场类型获取K线请求头"""
        if market in ["hk_stock", "us_stock", "a_stock", "jp_stock"]:
            return {
                "Org-Data-Enable": "false",
                "Dept-Code": "FIU",
                "Tenant-Id": "431500",
                "User-Agent": "FIU-Stock-Scanner/1.0",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive",
                "Fiu-Auth": f"bearer {self._get_current_bearer_token(fiu_auth=True)}",
            }
        elif market == "us_otc":
            return {
                "Org-Data-Enable": "false",
                "User-Agent": "FIU-Stock-Scanner/1.0",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive",
                "Fiu-Auth": f"bearer {self._get_current_bearer_token(fiu_auth=True)}",
            }
        else:
            return {}

    def _build_kline_payload(
        self, stock_code: str, market: str, kline_type: int, num_records: int
    ) -> Dict[str, Any]:
        """构建K线请求payload"""
        from datetime import datetime

        current_date = datetime.now().strftime("%Y-%m-%d")
        if kline_type > 4:
            # yyyy-MM-dd HH:mm:ss
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if market in ["hk_stock", "us_stock", "a_stock", "jp_stock"]:
            return {
                "candleMode": 0,
                "date": current_date,
                "number": min(num_records, 1000),  # 限制最大条数
                "orderMode": 0,  # 0: 降序 (最新在前)
                "symbol": stock_code,
                "timeMode": 0,
                "type": kline_type,
            }
        elif market == "us_otc":
            symbol = (
                stock_code.replace(".us", "")
                if stock_code.endswith(".us")
                else stock_code
            )
            return {
                "timeMode": 0,
                "date": current_date,
                "number": min(num_records, 1000),
                "symbol": symbol,
                "type": kline_type,
            }
        else:
            return {}

    def _parse_kline_response(
        self, data: Dict[str, Any], market: str
    ) -> Optional[List[Dict[str, Any]]]:
        """解析K线响应数据"""
        try:
            if market == "us_otc":
                if data.get("code") == 200 and data.get("data"):
                    return data["data"]
            else:
                if (
                    data.get("code") == 200
                    and data.get("success")
                    and data.get("data", {}).get("records")
                ):
                    return data["data"]["records"]

            return None

        except Exception as e:
            self.logger.error(f"解析K线响应失败: {str(e)}")
            return None

    def _format_kline_dataframe(
        self, kline_data: List[Dict[str, Any]], market: str
    ) -> pd.DataFrame:
        """将K线数据转换为标准DataFrame格式"""
        try:
            formatted_data = []

            # Market parameter reserved for future market-specific formatting
            _ = market

            for item in kline_data:
                formatted_item = {
                    "date": item.get("date"),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": float(item.get("volume", 0)),
                    "amount": float(item.get("amount", 0)),
                    "change": float(item.get("change", 0)),
                    "change_rate": float(item.get("changeRate", 0)),
                    "turnover_rate": (
                        float(item.get("turnoverRate", 0))
                        if item.get("turnoverRate")
                        else None
                    ),
                    "pre_close": float(item.get("preClose", 0)),
                }
                formatted_data.append(formatted_item)

            # 创建DataFrame
            df = pd.DataFrame(formatted_data)
            return df

        except Exception as e:
            self.logger.error(f"格式化K线DataFrame失败: {str(e)}")
            return pd.DataFrame()

    def get_realtime_price(
        self, stock_code: str, market: str, include_extended: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        获取实时价格数据

        Args:
            stock_code: 股票代码 (e.g., '00700.hk', 'TSLA.us', '000001.sz', 'DIDIY.us', '6758.jp')
            market: 市场类型 ('hk_stock', 'us_stock', 'a_stock', 'us_otc', 'jp_stock')
            include_extended: 是否包含扩展行情数据

        Returns:
            Dict: 实时价格信息，包含current_price, change_pct, volume, market_value等字段
        """
        try:
            self.logger.debug(f"FIU获取实时价格: {stock_code}, 市场: {market}")

            # 获取基础行情数据
            quote_data = self._get_quote_data(stock_code, market)
            if not quote_data:
                return None

            result = quote_data

            # 如果需要扩展数据，则获取扩展行情
            if include_extended:
                extended_data = self._get_extended_data(stock_code, market)
                if extended_data:
                    result.update(extended_data)

            return result

        except Exception as e:
            self.logger.error(
                f"获取实时价格失败: {stock_code}, {market}, 错误: {str(e)}"
            )
            return None

    def _get_quote_data(self, stock_code: str, market: str) -> Optional[Dict[str, Any]]:
        """获取基础行情数据"""
        try:
            if market not in self.endpoints:
                self.logger.error(f"不支持的市场类型: {market}")
                return None

            url = self.endpoints[market]["quote"]
            headers = self._get_headers(market)
            payload = self._build_quote_payload(stock_code, market)

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=10
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_quote_response(data, market)

        except Exception as e:
            self.logger.error(f"获取基础行情失败: {str(e)}")
            return None

    def _get_extended_data(
        self, stock_code: str, market: str
    ) -> Optional[Dict[str, Any]]:
        """获取扩展行情数据"""
        try:
            url = self.endpoints[market]["extend"]
            headers = self._get_headers(market)
            payload = self._build_extended_payload(stock_code, market)

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=10
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_extended_response(data, market)

        except Exception as e:
            self.logger.error(f"获取扩展行情失败: {str(e)}")
            return None

    def _get_headers(self, market: str) -> Dict[str, str]:
        """根据市场类型获取对应的请求头"""
        base_headers = {
            "User-Agent": "FIU-Stock-Scanner/1.0",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

        if market in ["hk_stock", "us_stock", "a_stock"]:
            bearer_token = self._get_current_bearer_token()
            base_headers["Authorization"] = f"Bearer {bearer_token}"
        elif market in ["us_otc", "jp_stock"]:
            bearer_token = self._get_current_bearer_token()
            base_headers["Fiu-Auth"] = f"Bearer {bearer_token}"
            if market == "jp_stock":
                base_headers.update(
                    {
                        "Org-Data-Enable": "false",
                        "Dept-Code": "FIU",
                        "Tenant-Id": "431500",
                        "Authorization": "Basic Zml1OmZpdV9zZWNyZXQ",
                    }
                )

        return base_headers

    def _build_quote_payload(self, stock_code: str, market: str) -> Dict[str, Any]:
        """构建基础行情请求payload"""
        if market == "hk_stock":
            return {
                "fields": ["snapshot", "order", "trade"],
                "symbols": [stock_code],
                "timeMode": 0,
            }
        elif market == "us_stock":
            return {
                "fields": ["snapshot", "order", "trade"],
                "sessionId": 1,
                "symbols": [stock_code],
                "timeMode": 0,
            }
        elif market == "a_stock":
            return {
                "fields": ["snapshot", "order", "trade"],
                "symbols": [stock_code],
                "timeMode": 0,
            }
        elif market == "us_otc":
            return {"timeMode": 0, "sessionId": 1, "symbol": stock_code}
        elif market == "jp_stock":
            return {"isSimple": 0, "symbols": [stock_code], "timeMode": 0}
        else:
            return {}

    def _build_extended_payload(self, stock_code: str, market: str) -> Dict[str, Any]:
        """构建扩展行情请求payload"""
        if market in ["hk_stock", "us_stock", "a_stock"]:
            return {"symbols": [stock_code], "timeMode": 0}
        elif market in ["us_otc", "jp_stock"]:
            symbol = stock_code.replace(".us", "") if market == "us_otc" else stock_code
            return {
                "timeMode": 0,
                "sessionId": 1 if market == "us_otc" else None,
                "symbol": symbol if market == "us_otc" else None,
                "symbols": [stock_code] if market == "jp_stock" else None,
            }
        else:
            return {}

    def _parse_quote_response(
        self, data: Dict[str, Any], market: str
    ) -> Optional[Dict[str, Any]]:
        """解析基础行情响应数据"""
        try:
            if market == "us_otc":
                if data.get("code") == 200 and data.get("success"):
                    item = data["data"]
                    return self._format_otc_quote_data(item)
            elif market == "jp_stock":
                if data.get("code") == 200 and data.get("success") and data.get("data"):
                    item = data["data"][0]
                    return self._format_jp_quote_data(item)
            else:
                if data.get("code") == "200" and data.get("body"):
                    item = data["body"][0]
                    return self._format_standard_quote_data(item, market)

            return None

        except Exception as e:
            self.logger.error(f"解析行情数据失败: {str(e)}")
            return None

    def _parse_extended_response(
        self, data: Dict[str, Any], market: str
    ) -> Optional[Dict[str, Any]]:
        """解析扩展行情响应数据"""
        try:
            if market in ["us_otc", "jp_stock"]:
                if data.get("code") == 200 and data.get("success"):
                    item = data["data"][0] if market == "jp_stock" else data["data"]
                    return self._format_extended_data(item, market)
            else:
                if data.get("code") == "200" and data.get("body"):
                    item = data["body"][0]
                    return self._format_extended_data(item, market)

            return None

        except Exception as e:
            self.logger.error(f"解析扩展数据失败: {str(e)}")
            return None

    def _format_standard_quote_data(
        self, item: Dict[str, Any], market: str
    ) -> Dict[str, Any]:
        """格式化标准行情数据 (港股/美股/A股)"""
        snapshot = item.get("snapshot", {})
        order = item.get("order", {})
        trade = item.get("trade", {})

        # Market-specific name handling
        name = item.get("name")
        if market == "us_stock" and not name:
            name = item.get("nameCn") or item.get("nameEn")

        return {
            "symbol": item.get("symbol"),
            "name": name,
            "current_price": snapshot.get("last") or snapshot.get("close"),
            "open": snapshot.get("open"),
            "high": snapshot.get("high"),
            "low": snapshot.get("low"),
            "pre_close": snapshot.get("preClose"),
            "change": snapshot.get("change"),
            "change_rate": snapshot.get("changeRate"),
            "amplitude": snapshot.get("amplitude"),
            "volume": snapshot.get("volume"),
            "amount": snapshot.get("amount"),
            "avg_price": snapshot.get("avgPrice"),
            "time": snapshot.get("time"),
            "bid_list": order.get("bidList", []),
            "ask_list": order.get("askList", []),
            "last_trade": (
                {
                    "price": trade.get("price"),
                    "volume": trade.get("volume"),
                    "amount": trade.get("amount"),
                    "time": trade.get("time"),
                }
                if trade
                else None
            ),
        }

    def _format_otc_quote_data(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """格式化OTC行情数据"""
        return {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "current_price": item.get("lastPrice") or item.get("close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "pre_close": item.get("preClose"),
            "change": item.get("change"),
            "change_rate": item.get("changeRate"),
            "amplitude": item.get("amplitude"),
            "volume": item.get("volume"),
            "amount": item.get("amount"),
            "avg_price": item.get("avgPrice"),
            "time": item.get("time"),
            "market_status": item.get("marketStatus"),
            "security_status": item.get("securityStatus"),
        }

    def _format_jp_quote_data(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """格式化日股行情数据"""
        return {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "current_price": item.get("last") or item.get("close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "pre_close": item.get("preClose"),
            "change": item.get("change"),
            "change_rate": item.get("changeRate"),
            "amplitude": item.get("amplitude"),
            "volume": item.get("volume"),
            "amount": item.get("amount"),
            "avg_price": item.get("avgPrice"),
            "time": item.get("time"),
            "price_max": item.get("priceMax"),
            "price_min": item.get("priceMin"),
        }

    def _format_extended_data(
        self, item: Dict[str, Any], market: str
    ) -> Dict[str, Any]:
        """格式化扩展行情数据"""
        base_data = {
            "total_shares": item.get("totalShares"),
            "total_market_value": item.get("totalMarketValue"),
            "circulation_shares": item.get("circulationShares"),
            "circulation_market_value": item.get("circulationMarketValue"),
            "pe_lyr": item.get("perLyr"),
            "pe_ttm": item.get("perTtm"),
            "pb_ratio": item.get("pbr"),
            "turnover_rate": item.get("turnoverRate"),
            "volume_rate": item.get("volumeRate"),
            "week_52_high": item.get("week52High"),
            "week_52_low": item.get("week52Low"),
            "history_high": item.get("historyHigh"),
            "history_low": item.get("historyLow"),
            "trading_currency": item.get("tradingCurrency"),
        }

        if market in ["us_otc", "jp_stock"]:
            base_data.update(
                {
                    "market_cap_float": item.get("marketCapFloat"),
                    "market_cap_total": item.get("marketCapTotal"),
                    "shares_float": item.get("sharesFloat"),
                    "shares_out": item.get("sharesOut"),
                    "lot_size": item.get("lotSize"),
                }
            )
        else:
            base_data.update(
                {
                    "eps_lyr": item.get("epsLyr"),
                    "eps_ttm": item.get("epsTtm"),
                    "nav": item.get("nav"),
                    "roe": item.get("roe"),
                    "dividend_rate_lyr": item.get("dividendRateLyr"),
                    "dividend_rate_ttm": item.get("dividendRateTtm"),
                    "net_profit": item.get("netProfit"),
                    "gross_profit_rate": item.get("grossProfitRate"),
                    "profit_margin": item.get("profitMargin"),
                }
            )

        return {k: v for k, v in base_data.items() if v is not None}

    def get_index_quote(
        self, symbols: List[str], market: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取指数行情数据

        Args:
            symbols: 指数代码列表 (e.g., ['000001'] for A股上证指数, ['HY50201020.us'] for 美股指数)
            market: 市场类型 ('hk_stock', 'us_stock', 'a_stock')

        Returns:
            List[Dict]: 指数行情数据列表，包含指数名称、价格、涨跌幅等信息
        """
        try:
            self.logger.debug(f"FIU获取指数行情: {symbols}, 市场: {market}")

            # 获取指数行情数据
            index_data = self._get_index_quote_data(symbols, market)
            if not index_data:
                return None

            # 格式化返回数据
            return self._format_index_quote_data(index_data, market)

        except Exception as e:
            self.logger.error(f"获取指数行情失败: {symbols}, {market}, 错误: {str(e)}")
            return None

    def _get_index_quote_data(
        self, symbols: List[str], market: str
    ) -> Optional[Dict[str, Any]]:
        """获取指数行情原始数据"""
        try:
            url = self.endpoints[market]["index_quote"]
            if not url:
                self.logger.error(f"不支持的指数行情市场类型: {market}")
                return None

            headers = self._get_headers(market)
            payload = self._build_index_quote_payload(symbols, market)

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_index_quote_response(data, market)

        except Exception as e:
            self.logger.error(f"获取指数行情原始数据失败: {str(e)}")
            return None

    def _build_index_quote_payload(
        self, symbols: List[str], market: str
    ) -> Dict[str, Any]:
        """构建指数行情请求payload"""
        symbol_codes = []
        for symbol in symbols:
            if symbol.lower().endswith("hk"):
                symbol_code = symbol.split(".")[0]
                symbol_codes.append(symbol_code)
            else:
                symbol_codes.append(symbol)
        return {
            "timeMode": 0,
            "symbols": symbol_codes,
        }

    def _parse_index_quote_response(
        self, data: Dict[str, Any], market: str
    ) -> Optional[Dict[str, Any]]:
        """解析指数行情响应数据"""
        try:
            if str(data.get("code")) == "200" or str(data.get("code")) == "0":
                if data.get("data"):
                    return {"quotes": data["data"]}
                if data.get("body"):
                    return {"quotes": data["body"]}
            return None

        except Exception as e:
            self.logger.error(f"解析指数行情响应失败: {str(e)}")
            return None

    def _format_index_quote_data(
        self, data: Dict[str, Any], market: str
    ) -> List[Dict[str, Any]]:
        """格式化指数行情数据"""
        try:
            formatted_quotes = []
            quotes = data.get("quotes", [])

            for item in quotes:
                formatted_quote = {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "time": item.get("time"),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "last": item.get("last"),
                    "close": item.get("close"),
                    "pre_close": item.get("preClose"),
                    "avg_price": item.get("avgPrice"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "change": item.get("change"),
                    "change_rate": item.get("changeRate"),
                    "amplitude": item.get("amplitude"),
                    "week_52_high": item.get("week52High"),
                    "week_52_low": item.get("week52Low"),
                    "total_market_value": item.get("totalMarketValue"),
                    "circulation_market_value": item.get("circulationMarketValue"),
                    "per_ttm": item.get("perTtm"),
                    "per_lyr": item.get("perLyr"),
                    "turnover_rate": item.get("turnoverRate"),
                    "rise": item.get("rise"),
                    "flat": item.get("flat"),
                    "fall": item.get("fall"),
                }

                # 过滤掉None值
                formatted_quote = {
                    k: v for k, v in formatted_quote.items() if v is not None
                }
                formatted_quotes.append(formatted_quote)

            return formatted_quotes

        except Exception as e:
            self.logger.error(f"格式化指数行情数据失败: {str(e)}")
            return []

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            bool: True if available, False otherwise
        """
        if self._available:
            return True
        try:
            # 尝试获取A股简单行情数据来测试连接
            test_result = self.get_realtime_price("000001.sz", "a_stock")
            self._available = test_result is not None
        except Exception as e:
            self.logger.warning(f"FIU API连接检查失败: {str(e)}")
        return self._available


class FiuFundamentalDataSource(BaseFundamentalDataSource):
    """FIU基本面数据源"""

    def __init__(self, api_tokens: Optional[Dict[str, str]] = None):
        """初始化FIU基本面数据源"""
        self.logger = logging.getLogger(__name__)
        self.name = "FIU"
        self._available = False

        # 获取token管理器
        self._token_manager = get_fiu_token_manager()

        # 从配置或环境变量中获取API tokens，如果没有则使用空值
        import os

        self.api_tokens = api_tokens or {
            "bearer_token": os.getenv("FIU_BEARER_TOKEN", ""),
        }

    def _get_current_bearer_token(self, fiu_auth: bool = False) -> str:
        """
        获取当前有效的bearer token

        Returns:
            str: 当前有效的token
        """
        if self._token_manager:
            token = self._token_manager.get_token(fiu_auth=fiu_auth)
            if token:
                return token

        # 如果token管理器不可用，回退到环境变量
        return self.api_tokens.get("bearer_token", "")

    def get_stock_info(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取股票基本信息，包括基本资料、公司资料和主营构成

        Args:
            stock_code: 股票代码 (如: 00700.hk, AAPL.us, 600519.sh)
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            Dict: 股票基本信息，包含基本资料、公司资料和主营构成数据
        """
        try:
            self.logger.debug(f"FIU获取股票基本信息: {stock_code}, 市场: {market}")

            # 验证市场类型
            if market not in ["a_stock", "hk_stock", "us_stock"]:
                self.logger.warning(f"不支持的市场类型: {market}")
                return {}

            result = {}

            # 获取基本资料
            basic_info = self._get_basic_info(stock_code, market)
            if basic_info:
                result["basic_info"] = basic_info

            # 获取公司资料
            company_info = self._get_company_info(stock_code, market)
            if company_info:
                result["company_info"] = company_info

            # 获取主营构成
            business_segments = self._get_business_segments(stock_code, market)
            if business_segments:
                result["business_segments"] = business_segments

            return result

        except Exception as e:
            self.logger.error(
                f"获取股票基本信息失败: {stock_code}, {market}, 错误: {str(e)}"
            )
            return {}

    def _get_basic_info(self, stock_code: str, market: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基本资料

        Args:
            stock_code: 股票代码
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            Dict: 基本资料信息
        """
        try:
            url = self._get_basic_info_url(market)
            if not url:
                return None

            headers = self._get_stock_info_headers()
            payload = {"symbol": stock_code}

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                return self._format_basic_info(data["data"][0], market)

            return None

        except Exception as e:
            self.logger.error(f"获取基本资料失败: {str(e)}")
            return None

    def _get_company_info(
        self, stock_code: str, market: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取公司资料

        Args:
            stock_code: 股票代码
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            Dict: 公司资料信息
        """
        try:
            url = self._get_company_info_url(market)
            if not url:
                return None

            headers = self._get_stock_info_headers()
            payload = {"symbol": stock_code}

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                return self._format_company_info(data["data"][0], market)

            return None

        except Exception as e:
            self.logger.error(f"获取公司资料失败: {str(e)}")
            return None

    def _get_business_segments(
        self, stock_code: str, market: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取主营构成数据

        Args:
            stock_code: 股票代码
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            List[Dict]: 主营构成数据列表
        """
        try:
            url = self._get_business_segments_url(market)
            if not url:
                return None

            headers = self._get_stock_info_headers()
            payload = {"symbol": stock_code}

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                return self._format_business_segments(data["data"], market)

            return None

        except Exception as e:
            self.logger.error(f"获取主营构成失败: {str(e)}")
            return None

    def _get_basic_info_url(self, market: str) -> Optional[str]:
        """获取基本资料API URL"""
        urls = {
            "hk_stock": "https://globaldata1-ali.szfuit.com/api/hk/f10/summary/basic",
            "us_stock": "https://globaldata1-ali.szfuit.com/api/us/f10/summary/basic",
            "a_stock": "https://globaldata1-ali.szfuit.com/api/hs/f10/summary/basic",
        }
        return urls.get(market)

    def _get_company_info_url(self, market: str) -> Optional[str]:
        """获取公司资料API URL"""
        urls = {
            "hk_stock": "https://globaldata1-ali.szfuit.com/api/hk/f10/summary/com-info",
            "us_stock": "https://globaldata1-ali.szfuit.com/api/us/f10/summary/com-info",
            "a_stock": "https://globaldata1-ali.szfuit.com/api/hs/f10/summary/com-info",
        }
        return urls.get(market)

    def _get_business_segments_url(self, market: str) -> Optional[str]:
        """获取主营构成API URL"""
        urls = {
            "hk_stock": "https://globaldata1-ali.szfuit.com/api/hk/f10/finance/segment",
            "us_stock": "https://globaldata1-ali.szfuit.com/api/us/f10/finance/segment",
            "a_stock": "https://globaldata1-ali.szfuit.com/api/hs/f10/finance/segment",
        }
        return urls.get(market)

    def _get_stock_info_headers(self) -> Dict[str, str]:
        """获取股票信息请求头"""
        bearer_token = self._get_current_bearer_token()
        return {
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "FIU-Stock-Scanner/1.0",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

    def _format_basic_info(self, data: Dict[str, Any], market: str) -> Dict[str, Any]:
        """格式化基本资料数据"""
        if market == "hk_stock":
            return {
                "symbol": data.get("symbol"),
                "name": data.get("cnName"),
                "security_type": data.get("secType"),
                "lot_size": data.get("lotSize"),
                "total_shares": data.get("totalShares"),
                "float_shares": data.get("floatShares"),
                "eps": data.get("eps"),
                "eps_ttm": data.get("epsTtm"),
                "bvps": data.get("bvps"),
                "dividend_ttm": data.get("dividendTtm"),
                "dividend_rate_ttm": data.get("dividendRateTtm"),
                "month_average_vol": data.get("monthAverageVol"),
                "year_high": data.get("yearHigh"),
                "year_low": data.get("yearLow"),
            }
        elif market == "us_stock":
            return {
                "symbol": data.get("symbol"),
                "name": data.get("cnName"),
                "security_type": data.get("secType"),
                "lot_size": data.get("lotSize"),
                "total_shares": data.get("totalShares"),
                "float_shares": data.get("floatShares"),
                "eps": data.get("eps"),
                "eps_ttm": data.get("epsTtm"),
                "bvps": data.get("bvps"),
                "dividend_ttm": data.get("dividendTtm"),
                "dividend_rate_ttm": data.get("dividendRateTtm"),
                "month_average_vol": data.get("monthAverageVol"),
                "year_high": data.get("yearHigh"),
                "year_low": data.get("yearLow"),
                "asset_class": data.get("assetClass"),
                "dividend_distribution": data.get("dividendDistribution"),
            }
        elif market == "a_stock":
            return {
                "symbol": data.get("symbol"),
                "name": data.get("cnName"),
                "security_type": data.get("secType"),
                "lot_size": data.get("lotSize"),
                "total_shares": data.get("totalShares"),
                "float_shares": data.get("floatShares"),
                "eps": data.get("eps"),
                "eps_ttm": data.get("epsTtm"),
                "bvps": data.get("bvps"),
                "dividend_ttm": data.get("dividendTtm"),
                "dividend_rate_ttm": data.get("dividendRateTtm"),
                "month_average_vol": data.get("monthAverageVol"),
            }
        return {}

    def _format_company_info(self, data: Dict[str, Any], market: str) -> Dict[str, Any]:
        """格式化公司资料数据"""
        base_info = {
            "symbol": data.get("symbol"),
            "list_date": data.get("listDate"),
            "company_name_cn": data.get("cnComName"),
            "company_name_en": data.get("enComName"),
            "business_description": data.get("comBusiness"),
            "company_profile": data.get("comProfile"),
            "chairman": data.get("chairman"),
            "company_secretary": data.get("companySecretary"),
            "company_address": data.get("comAddress"),
            "reg_address": data.get("regAddress") or data.get("regAdress"),
            "telephone": data.get("telephone"),
            "fax": data.get("fax"),
            "email": data.get("email"),
            "website": data.get("website"),
            "employees_count": data.get("numberOfEmployees"),
            "period_end_date": data.get("periodEndDate"),
            "isin": data.get("isin"),
        }

        if market == "hk_stock":
            base_info.update(
                {
                    "industry": data.get("industry"),
                    "market": data.get("market"),
                    "auditors": data.get("auditors"),
                    "share_registrar": data.get("shareRegistrar"),
                    "value_currency": data.get("valueCurrency"),
                    "per_value": data.get("perValue"),
                    "founded_date": data.get("foundDate"),
                }
            )
        elif market == "us_stock":
            base_info.update(
                {
                    "country": data.get("country"),
                    "city": data.get("city"),
                    "province": data.get("province"),
                    "post_code": data.get("postCode"),
                    "security_type": data.get("secType"),
                    "main_exchange": data.get("mainExchange"),
                    "issue_price": data.get("issuePrice"),
                    "issue_share": data.get("issueShare"),
                    "per_value": data.get("perValue"),
                    "value_currency": data.get("valueCurrency"),
                    "founded_date": data.get("foundDate"),
                }
            )
        elif market == "a_stock":
            base_info.update(
                {
                    "industry": data.get("industry"),  # 在A股文档中没有看到，但可能存在
                    "market": data.get("market"),
                    "province": data.get("province"),
                    "post_code": data.get("postCode"),
                    "company_type": data.get("comType"),
                    "auditors": data.get("auditors"),
                    "legal_representative": data.get("legalRepresentative"),
                    "securities_representative": data.get("secRepresentative"),
                    "business_license_number": data.get("numberOfBR"),
                    "legal_adviser": data.get("legalAdviser"),
                    "founded_date": data.get("foundDate"),
                }
            )

        return base_info

    def _format_business_segments(
        self, data_list: List[Dict[str, Any]], market: str
    ) -> List[Dict[str, Any]]:
        """格式化主营构成数据"""
        formatted_segments = []

        for item in data_list:
            segment = {
                "symbol": item.get("symbol"),
                "report_date": item.get("reportDate"),
                "report_type": item.get("reportType"),
                "segment_name": item.get("name"),
                "segment_type": item.get("segmentType"),
                "operating_income": item.get("operatingIncome"),
                "income_ratio": item.get("incomeRatio"),
                "currency": item.get("currency"),
            }

            if market == "hk_stock":
                segment.update(
                    {
                        "cover_months": item.get("coverMonths"),
                        "operating_income_yoy": item.get("operatingIncomeYoY"),
                    }
                )
            elif market == "us_stock":
                segment.update(
                    {
                        "operating_income_yoy": item.get("operatingIncomeYOY"),
                        "name_cn": item.get("nameCN"),
                    }
                )
            elif market == "a_stock":
                segment.update(
                    {
                        "cover_months": item.get("coverMonths"),
                        "operating_cost": item.get("operatingCost"),
                        "cost_ratio": item.get("costRatio"),
                        "operating_profit": item.get("operatingProfit"),
                        "profit_ratio": item.get("profitRatio"),
                        "operating_income_yoy": item.get("operatingIncomeYoY"),
                        "operating_cost_yoy": item.get("operatingCostYoY"),
                        "operating_profit_yoy": item.get("operatingProfitYoY"),
                    }
                )

            formatted_segments.append(segment)

        return formatted_segments

    def get_financial_indicators(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取财务指标数据 - 获取港美A股财务三大表数据

        Args:
            stock_code: 股票代码 (如: 00700.hk, TSLA.us, 000001.sz)
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            Dict: 财务三大表数据和关键财务指标，包含利润表、资产负债表、现金流量表的最新数据

        Note:
            如果API认证失败(401错误)，
            说明token可能已过期，需要更新API配置中的bearer_token。
        """
        try:
            self.logger.debug(f"FIU获取财务三大表数据: {stock_code}, 市场: {market}")

            # 验证市场类型
            if market not in ["a_stock", "hk_stock", "us_stock"]:
                self.logger.warning(f"不支持的市场类型: {market}")
                return {}

            # 获取当前日期作为结束日期
            from datetime import datetime, timedelta

            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

            result = {}
            auth_error_count = 0

            # 获取利润表数据
            income_data = self._get_income_statement(
                stock_code, market, start_date, end_date
            )
            if income_data:
                result["income_statement"] = income_data
            elif self._is_auth_error():
                auth_error_count += 1

            # 获取资产负债表数据
            balance_data = self._get_balance_sheet(
                stock_code, market, start_date, end_date
            )
            if balance_data:
                result["balance_sheet"] = balance_data
            elif self._is_auth_error():
                auth_error_count += 1

            # 获取现金流量表数据
            cash_flow_data = self._get_cash_flow(
                stock_code, market, start_date, end_date
            )
            if cash_flow_data:
                result["cash_flow"] = cash_flow_data
            elif self._is_auth_error():
                auth_error_count += 1

            # 如果多个请求都返回认证错误，给出明确提示
            if auth_error_count >= 2 and not result:
                self.logger.warning(
                    f"检测到认证错误，请检查API token是否已过期: {stock_code}"
                )
                result["error"] = "API认证失败，请检查token配置"

            return result

        except Exception as e:
            self.logger.error(
                f"获取财务三大表数据和关键指标失败: {stock_code}, {market}, 错误: {str(e)}"
            )
            return {}

    def _is_auth_error(self) -> bool:
        """检查是否为认证错误"""
        # 这个方法可以在后续扩展时添加更多的认证错误检测逻辑
        return False

    def _get_year_report_type(self, market: str) -> str:
        report_dict = {
            "hk_stock": "F",
            "us_stock": "FY",
            "a_stock": "12",
        }
        return report_dict.get(market, "")

    def _get_income_statement(
        self, stock_code: str, market: str, start_date: str, end_date: str
    ) -> Optional[Dict[str, Any]]:
        """获取利润表数据"""
        try:
            url = self._get_financial_url(market, "income")
            if not url:
                return None

            headers = self._get_financial_headers()
            payload = {
                "symbol": stock_code,
                "startDate": start_date,
                "endDate": end_date,
                "sort": "desc",
            }
            reportType = self._get_year_report_type(market)
            if reportType:
                payload["reportType"] = reportType

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                # 返回最新的报表数据（第一条记录）
                latest_data = data["data"][0] if data["data"] else None
                if latest_data:
                    return self._format_income_data(latest_data)

            return None

        except Exception as e:
            self.logger.error(f"获取利润表数据失败: {str(e)}")
            return None

    def _get_balance_sheet(
        self, stock_code: str, market: str, start_date: str, end_date: str
    ) -> Optional[Dict[str, Any]]:
        """获取资产负债表数据"""
        try:
            url = self._get_financial_url(market, "balance")
            if not url:
                return None

            headers = self._get_financial_headers()
            payload = {
                "symbol": stock_code,
                "startDate": start_date,
                "endDate": end_date,
                "sort": "desc",
            }
            reportType = self._get_year_report_type(market)
            if reportType:
                payload["reportType"] = reportType

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                # 返回最新的报表数据（第一条记录）
                latest_data = data["data"][0] if data["data"] else None
                if latest_data:
                    return self._format_balance_data(latest_data)

            return None

        except Exception as e:
            self.logger.error(f"获取资产负债表数据失败: {str(e)}")
            return None

    def _get_cash_flow(
        self, stock_code: str, market: str, start_date: str, end_date: str
    ) -> Optional[Dict[str, Any]]:
        """获取现金流量表数据"""
        try:
            url = self._get_financial_url(market, "cash")
            if not url:
                return None

            headers = self._get_financial_headers()
            payload = {
                "symbol": stock_code,
                "startDate": start_date,
                "endDate": end_date,
                "sort": "desc",
            }
            reportType = self._get_year_report_type(market)
            if reportType:
                payload["reportType"] = reportType

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                # 返回最新的报表数据（第一条记录）
                latest_data = data["data"][0] if data["data"] else None
                if latest_data:
                    return self._format_cash_flow_data(latest_data)

            return None

        except Exception as e:
            self.logger.error(f"获取现金流量表数据失败: {str(e)}")
            return None

    def _get_financial_url(self, market: str, statement_type: str) -> Optional[str]:
        """根据市场类型和报表类型获取财务数据API端点"""
        financial_urls = {
            "hk_stock": {
                "income": "https://globaldata1-ali.szfuit.com/api/hk/f10/finance/income",
                "balance": "https://globaldata1-ali.szfuit.com/api/hk/f10/finance/balance",
                "cash": "https://globaldata1-ali.szfuit.com/api/hk/f10/finance/cash",
                "key-indicator": "https://globaldata1-ali.szfuit.com/api/hk/f10/finance/key-indicator",
            },
            "us_stock": {
                "income": "https://globaldata1-ali.szfuit.com/api/us/f10/finance/income-basic",
                "balance": "https://globaldata1-ali.szfuit.com/api/us/f10/finance/balance-basic",
                "cash": "https://globaldata1-ali.szfuit.com/api/us/f10/finance/cash-basic",
                "key-indicator": "https://globaldata1-ali.szfuit.com//api/us/f10/finance/key-indicator",  # v2 字段不一样.
            },
            "a_stock": {
                "income": "https://globaldata1-ali.szfuit.com/api/hs/f10/finance/income",
                "balance": "https://globaldata1-ali.szfuit.com/api/hs/f10/finance/balance",
                "cash": "https://globaldata1-ali.szfuit.com/api/hs/f10/finance/cash",
                "key-indicator": "https://globaldata1-ali.szfuit.com/api/hs/f10/finance/key-indicator",
            },
        }

        return financial_urls.get(market, {}).get(statement_type)

    def _get_financial_headers(self) -> Dict[str, str]:
        """获取财务数据请求头"""
        bearer_token = self._get_current_bearer_token()
        return {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

    def _format_income_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化利润表数据"""
        # 基础字段
        formatted_data = {
            "symbol": data.get("symbol"),
            "sec_name": data.get("secName"),
            "report_date": data.get("reportDate"),
            "report_type": data.get("reportType"),
            "currency": data.get("currency"),
            "cover_months": data.get("coverMonths"),
            "report_kind": data.get("reportKind"),
            "auditors_opinion": data.get("auditorsOpinion"),
            "opinion_name": data.get("opinionName"),
            "standard_code": data.get("standardCode"),
            "org_name": data.get("orgName"),
        }

        # 营收相关
        formatted_data.update(
            {
                "operating_income": data.get("operatingIncome"),
                "operating_income_yoy": data.get("operatingIncomeYoY"),
                "operating_income_growth": data.get("operatingIncomeGrowth"),
                "total_operating_income": data.get("totalOperIncome"),
                "total_operating_income_yoy": data.get("totalOperIncomeYoY"),
                "gross_profit": data.get("grossProfit"),
                "gross_profit_yoy": data.get("grossProfitYoY"),
                "gross_profit_margin": data.get("grossProfitMargin"),
                "gross_profit_margin_yoy": data.get("grossProfitMarginYoY"),
            }
        )

        # 成本相关
        formatted_data.update(
            {
                "operating_cost": data.get("operatingCost"),
                "operating_cost_yoy": data.get("operatingCostYoY"),
                "total_operating_cost": data.get("totalOperCost"),
                "total_operating_cost_yoy": data.get("totalOperCostYoY"),
            }
        )

        # 利润相关
        formatted_data.update(
            {
                "operating_profit": data.get("operProfit")
                or data.get("operatingProfit"),
                "operating_profit_yoy": data.get("operProfitYoY")
                or data.get("operatingProfitYoY"),
                "core_operating_profit": data.get("coreOperatingProfit"),
                "core_operating_profit_yoy": data.get("coreOperatingProfitYoY"),
                "core_profit": data.get("coreProfit"),
                "core_profit_yoy": data.get("coreProfitYoY"),
                "net_profit": data.get("netProfit") or data.get("netIncome"),
                "net_profit_yoy": data.get("netProfitYoY") or data.get("netIncomeYoY"),
                "net_profit_growth": data.get("netProfitGrowth"),
                "net_income_ratio": data.get("netIncomeRatio"),
                "net_income_ratio_yoy": data.get("netIncomeRatioYoY"),
                "total_profit": data.get("totalProfit"),
                "total_profit_yoy": data.get("totalProfitYoY"),
                "profit_before_taxation": data.get("profitBeforeTaxation")
                or data.get("pretaxIncome"),
                "profit_before_taxation_yoy": data.get("profitBeforeTaxationYoY")
                or data.get("pretaxIncomeYoY"),
                "profit_the_period": data.get("profitThePeriod"),
                "profit_the_period_yoy": data.get("profitThePeriodYoY"),
            }
        )

        # 归属母公司相关
        formatted_data.update(
            {
                "owners_of_the_com": data.get("ownersOfTheCom"),
                "owners_of_the_com_yoy": data.get("ownersOfTheComYoY"),
                "owners_of_the_com_net": data.get("ownersOfTheComNet"),
                "owners_of_the_com_net_yoy": data.get("ownersOfTheComNetYoY"),
                "net_profit_parent_com": data.get("netProfitParentCom"),
                "net_profit_parent_com_yoy": data.get("netProfitParentComYoY"),
                "net_income_avail_to_common": data.get("netIncomeAvailToCommon"),
                "net_income_avail_to_common_yoy": data.get("netIncomeAvailToCommonYoY"),
                "consolidated_net_income": data.get("consolidatedNetIncome"),
                "consolidated_net_income_yoy": data.get("consolidatedNetIncomeYoY"),
            }
        )

        # 每股收益
        formatted_data.update(
            {
                "basic_eps": data.get("basicEPS") or data.get("eps"),
                "basic_eps_yoy": data.get("basicEPSYoY") or data.get("epsYoY"),
                "diluted_eps": data.get("dilutedEPS") or data.get("epsFullyDiluted"),
                "diluted_eps_yoy": data.get("dilutedEPSYoY")
                or data.get("epsFullyDilutedYoY"),
                "adjusted_basic_eps": data.get("adjustedBasicEPS"),
                "adjusted_basic_eps_yoy": data.get("adjustedBasicEPSYoY"),
                "adjusted_basic_eps_growth": data.get("adjustedBasicEPSGrowth"),
                "adjusted_diluted_eps": data.get("adjustedDilutedEPS"),
                "adjusted_diluted_eps_yoy": data.get("adjustedDilutedEPSYoY"),
                "weighted_ave_share_number": data.get("weightedAveShareNumber"),
            }
        )

        # 费用相关
        formatted_data.update(
            {
                "operating_expenses": data.get("operatingExpenses"),
                "operating_expenses_yoy": data.get("operatingExpensesYoY"),
                "total_operating_expenses": data.get("totalOperatingExpenses"),
                "total_operating_expenses_yoy": data.get("totalOperatingExpensesYoY"),
                "general_admin_expenses": data.get("generalAdminExpenses"),
                "general_admin_expenses_yoy": data.get("generalAdminExpensesYoY"),
                "oper_admin_expense": data.get("operAdminExpense"),
                "oper_admin_expense_yoy": data.get("operAdminExpenseYoY"),
                "admin_expense": data.get("adminExpense"),
                "admin_expense_yoy": data.get("adminExpenseYoY"),
                "sale_expense": data.get("saleExpense"),
                "sale_expense_yoy": data.get("saleExpenseYoY"),
                "sell_expense": data.get("sellExpense"),
                "sell_expense_yoy": data.get("sellExpenseYoY"),
                "other_operating_expenses": data.get("otherOperatingExpenses"),
                "other_operating_expenses_yoy": data.get("otherOperatingExpensesYoY"),
                "research_expense": data.get("researchExpense")
                or data.get("rdExpenses"),
                "research_expense_yoy": data.get("researchExpenseYoY")
                or data.get("rdExpensesYoY"),
            }
        )

        # 利率和税收
        formatted_data.update(
            {
                "interest_expense": data.get("interestExpense"),
                "interest_expense_yoy": data.get("interestExpenseYoY"),
                "interest_income": data.get("interestIncome"),
                "interest_income_yoy": data.get("interestIncomeYoY"),
                "finance_cost": data.get("financeCost") or data.get("finaCost"),
                "finance_cost_yoy": data.get("financeCostYoY")
                or data.get("finaCostYoY"),
                "taxation": data.get("taxation") or data.get("incomeTaxExpense"),
                "taxation_yoy": data.get("taxationYoY")
                or data.get("incomeTaxExpenseYoY"),
                "taxation_rate": data.get("taxationRate"),
            }
        )

        # 银行业特有字段
        formatted_data.update(
            {
                "interest_net_income": data.get("interestNetIncome"),
                "interest_net_income_yoy": data.get("interestNetIncomeYoY"),
                "commission_net_income": data.get("commissionNetIncome"),
                "commission_net_income_yoy": data.get("commissionNetIncomeYoY"),
                "commission_income": data.get("commissionIncome"),
                "commission_income_yoy": data.get("commissionIncomeYoY"),
                "commission_expanse": data.get("commissionExpanse"),
                "commission_expanse_yoy": data.get("commissionExpanseYoY"),
                "net_interest_income": data.get("netInterestIncome"),
                "net_interest_income_yoy": data.get("netInterestIncomeYoY"),
                "non_interest_income": data.get("nonInterestIncome"),
                "non_interest_income_yoy": data.get("nonInterestIncomeYoY"),
                "non_interest_expense": data.get("nonInterestExpense"),
                "non_interest_expense_yoy": data.get("nonInterestExpenseYoY"),
                "loan_loss_provision": data.get("loanLossProvision"),
                "loan_loss_provision_yoy": data.get("loanLossProvisionYoY"),
                "credit_impair_loss_in_cost": data.get("creditImpairLossInCost"),
                "credit_impair_loss_in_cost_yoy": data.get("creditImpairLossInCostYoY"),
                "asset_impairment_loss": data.get("assetImpairmentLoss"),
                "asset_impairment_loss_yoy": data.get("assetImpairmentLossYoY"),
            }
        )

        # 综合收益
        formatted_data.update(
            {
                "total_comprehensive_income": data.get("totalComprehensiveIncome"),
                "total_comprehensive_income_yoy": data.get(
                    "totalComprehensiveIncomeYoY"
                ),
                "other_comprehensive_income": data.get("otherComprehensiveIncome"),
                "other_comprehensive_income_yoy": data.get(
                    "otherComprehensiveIncomeYoY"
                ),
            }
        )

        # 其他收入和投资收益
        formatted_data.update(
            {
                "other_income": data.get("otherIncome"),
                "other_income_yoy": data.get("otherIncomeYoY"),
                "other_oper_revenue": data.get("otherOperRevenue"),
                "other_oper_revenue_yoy": data.get("otherOperRevenueYoY"),
                "inv_income": data.get("invIncome"),
                "inv_income_yoy": data.get("invIncomeYoY"),
                "fair_value_change": data.get("fairValueChange"),
                "fair_value_change_yoy": data.get("fairValueChangeYoY"),
                "fair_value_change_net_income": data.get("fairValueChangeNetIncome"),
                "fair_value_change_net_income_yoy": data.get(
                    "fairValueChangeNetIncomeYoY"
                ),
                "exchange_gain": data.get("exchangeGain"),
                "exchange_gain_yoy": data.get("exchangeGainYoY"),
                "asset_disposal_income": data.get("assetDisposalIncome"),
                "asset_disposal_income_yoy": data.get("assetDisposalIncomeYoY"),
                "join_contr_entities_associates": data.get(
                    "joinContrEntitiesAssociates"
                ),
                "join_contr_entities_associates_yoy": data.get(
                    "joinContrEntitiesAssociatesYoY"
                ),
                "equity_in_earnings_of_affiliates": data.get(
                    "equityInEarningsOfAffiliates"
                ),
                "equity_in_earnings_of_affiliates_yoy": data.get(
                    "equityInEarningsOfAffiliatesYoY"
                ),
            }
        )

        # 财务指标
        formatted_data.update(
            {
                "return_on_equity": data.get("returnOnEquity"),
                "return_on_equity_yoy": data.get("returnOnEquityYoY"),
                "return_on_total_assets": data.get("returnOnTotalAssets"),
                "return_on_total_assets_yoy": data.get("returnOnTotalAssetsYoY"),
                "ebitda": data.get("ebitDA") or data.get("ebitda"),
                "ebitda_yoy": data.get("ebitDAYoY") or data.get("ebitdaYoY"),
                "ebitda_ratio": data.get("ebitDARatio"),
                "ebitda_ratio_yoy": data.get("ebitDARatioYoY"),
                "ebitda_margin": data.get("ebitdaMargin"),
                "ebitda_margin_yoy": data.get("ebitdaMarginYoY")
                or data.get("ebitdaMarginYOY"),
                "ebita": data.get("ebita"),
                "ebita_yoy": data.get("ebitaYoY"),
            }
        )

        # 折旧摊销
        formatted_data.update(
            {
                "depreciation": data.get("depreciation"),
                "depreciation_yoy": data.get("depreciationYoY"),
                "depreciation_amortization": data.get("depreciationAmortization"),
                "depreciation_amortization_yoy": data.get(
                    "depreciationAmortizationYoY"
                ),
            }
        )

        # 股息相关
        formatted_data.update(
            {
                "common_share_dividend": data.get("commonShareDividend"),
                "common_share_dividend_yoy": data.get("commonShareDividendYoY"),
                "adjusted_dps": data.get("adjustedDPS"),
                "adjusted_dps_yoy": data.get("adjustedDPSYoY"),
                "preferred_dividends": data.get("preferredDividends"),
                "preferred_dividends_yoy": data.get("preferredDividendsYoY"),
            }
        )

        # 少数股东权益
        formatted_data.update(
            {
                "non_controlling_interests": data.get("nonControllingInterests"),
                "non_controlling_interests_yoy": data.get("nonControllingInterestsYoY"),
                "minority_interest_expense": data.get("minorityInterestExpense"),
                "minority_interest_expense_yoy": data.get("minorityInterestExpenseYoY"),
                "minority_profit": data.get("minorityProfit"),
                "minority_profit_yoy": data.get("minorityProfitYoY"),
            }
        )

        # 特殊项目 (根据市场不同可能存在)
        formatted_data.update(
            {
                "non_operating_items": data.get("nonOperatingItems"),
                "non_operating_items_yoy": data.get("nonOperatingItemsYoY"),
                "other_non_operating_items": data.get("otherNonOperatingItems"),
                "other_non_operating_items_yoy": data.get("otherNonOperatingItemsYoY"),
                "extraordinary_charge": data.get("extraordinaryCharge"),
                "extraordinary_charge_yoy": data.get("extraordinaryChargeYoY"),
                "non_oper_revenue": data.get("nonOperRevenue"),
                "non_oper_revenue_yoy": data.get("nonOperRevenueYoY"),
                "non_oper_expense": data.get("nonOperExpense"),
                "non_oper_expense_yoy": data.get("nonOperExpenseYoY"),
                "business_tax_surtax": data.get("businessTaxSurtax"),
                "business_tax_surtax_yoy": data.get("businessTaxSurtaxYoY"),
            }
        )

        # 汇率相关 (港股美股)
        formatted_data.update(
            {
                "rate_hkd": data.get("rateHKD"),
                "rate_usd": data.get("rateUSD"),
                "original_currency": data.get("originalCurrency"),
            }
        )

        # 持续经营
        formatted_data.update(
            {
                "continu_operat_net_profit": data.get("continuOperatNetProfit"),
                "continu_operat_net_profit_yoy": data.get("continuOperatNetProfitYoY"),
                "terminal_operat_net_profit": data.get("terminalOperatNetProfit"),
                "terminal_operat_net_profit_yoy": data.get(
                    "terminalOperatNetProfitYoY"
                ),
            }
        )

        # 过滤掉None值
        return {k: v for k, v in formatted_data.items() if v is not None}

    def _format_balance_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化资产负债表数据"""
        # 基础字段
        formatted_data = {
            "symbol": data.get("symbol"),
            "sec_name": data.get("secName"),
            "report_date": data.get("reportDate"),
            "report_type": data.get("reportType"),
            "currency": data.get("currency"),
            "cover_months": data.get("coverMonths"),
            "report_kind": data.get("reportKind"),
            "auditors_opinion": data.get("auditorsOpinion"),
            "opinion_name": data.get("opinionName"),
            "standard_code": data.get("standardCode"),
            "org_name": data.get("orgName"),
        }

        # 总体资产负债和权益
        formatted_data.update(
            {
                "total_assets": data.get("totalAsset") or data.get("totalAssets"),
                "total_assets_yoy": data.get("totalAssetYoY")
                or data.get("totalAssetsYoY"),
                "total_liabilities": data.get("totalLiab")
                or data.get("totalLiabilities"),
                "total_liabilities_yoy": data.get("totalLiabYoY")
                or data.get("totalLiabilitiesYoY"),
                "total_equity": data.get("totalSHEquity") or data.get("totalEquity"),
                "total_equity_yoy": data.get("totalSHEquityYoY")
                or data.get("totalEquityYoY"),
                "total_shareholders_equity": data.get("totalShareholdersEquity"),
                "total_shareholders_equity_yoy": data.get("totalShareholdersEquityYoY"),
                "net_assets": data.get("netAssets"),
                "net_assets_yoy": data.get("netAssetsYoY"),
                "liabilities_and_stockholders_equity": data.get(
                    "liabilitiesAndStockholdersEquity"
                ),
                "liabilities_and_stockholders_equity_yoy": data.get(
                    "liabilitiesAndStockholdersEquityYoY"
                ),
                "total_liab_sh_equity": data.get("totalLiabSHEquity"),
                "total_liab_sh_equity_yoy": data.get("totalLiabSHEquityYoY"),
            }
        )

        # 流动资产与负债
        formatted_data.update(
            {
                "total_current_assets": data.get("totalCurAssets")
                or data.get("totalCurrentAssets"),
                "total_current_assets_yoy": data.get("totalCurAssetsYoY")
                or data.get("totalCurrentAssetsYoY"),
                "total_current_liabilities": data.get("totalCurLiab")
                or data.get("totalCurrentLiabilities"),
                "total_current_liabilities_yoy": data.get("totalCurLiabYoY")
                or data.get("totalCurrentLiabilitiesYoY"),
                "net_current_assets": data.get("netCurrentAssets"),
                "net_current_assets_yoy": data.get("netCurrentAssetsYoY"),
                "quick_assets": data.get("quickAssets"),
                "quick_assets_yoy": data.get("quickAssetsYoY"),
            }
        )

        # 非流动资产与负债
        formatted_data.update(
            {
                "total_non_current_assets": data.get("totalNonCurrentAssets"),
                "total_non_current_assets_yoy": data.get("totalNonCurrentAssetsYoY"),
                "total_non_current_liab": data.get("totalNonCurrentLiab"),
                "total_non_current_liab_yoy": data.get("totalNonCurrentLiabYoY"),
                "total_assets_less_curr_liab": data.get("totalAssetsLessCurrLiab"),
                "total_assets_less_curr_liab_yoy": data.get(
                    "totalAssetsLessCurrLiabYoY"
                ),
            }
        )

        # 现金相关
        formatted_data.update(
            {
                "cash_deposit_in_cbank": data.get("cashDepositInCBank"),
                "cash_deposit_in_cbank_yoy": data.get("cashDepositInCBankYoY"),
                "cash_and_short_term_investments": data.get(
                    "cashAndShortTermInvestments"
                ),
                "cash_and_short_term_investments_yoy": data.get(
                    "cashAndShortTermInvestmentsYoY"
                ),
                "cash_and_near_cash": data.get("cashAndNearCash"),
                "cash_and_near_cash_yoy": data.get("cashAndNearCashYoY"),
                "total_cash": data.get("totalCash"),
                "total_cash_yoy": data.get("totalCashYoY"),
                "net_cash": data.get("netCash"),
                "net_cash_yoy": data.get("netCashYoY"),
                "total_cash_and_due_from_banks": data.get("totalCashAndDueFromBanks"),
                "total_cash_and_due_from_banks_yoy": data.get(
                    "totalCashAndDueFromBanksYoY"
                ),
            }
        )

        # 应收款项
        formatted_data.update(
            {
                "trade_debtors": data.get("tradeDebtors"),
                "trade_debtors_yoy": data.get("tradeDebtorsYoY"),
                "short_term_accounts_receivable": data.get(
                    "shortTermAccountsReceivable"
                ),
                "short_term_accounts_receivable_yoy": data.get(
                    "shortTermAccountsReceivableYoY"
                ),
                "accounts_payable": data.get("accountsPayable"),
                "accounts_payable_yoy": data.get("accountsPayableYoY"),
                "trade_creditors": data.get("tradeCreditors"),
                "trade_creditors_yoy": data.get("tradeCreditorsYoY"),
                "interest_receivables": data.get("interestReceivables"),
                "interest_receivables_yoy": data.get("interestReceivablesYoY"),
                "other_rec_includ_devident_interest": data.get(
                    "otherRecIncludDevidendInterest"
                ),
                "other_rec_includ_devident_interest_yoy": data.get(
                    "otherRecIncludDevidendInterestYoY"
                ),
            }
        )

        # 存货
        formatted_data.update(
            {
                "inventory": data.get("inventory"),
                "inventory_yoy": data.get("inventoryYoY"),
                "inventory_share": data.get("inventoryShare"),
                "inventory_share_yoy": data.get("inventoryShareYoY"),
            }
        )

        # 固定资产和无形资产
        formatted_data.update(
            {
                "fixed_assets": data.get("fixedAsset") or data.get("fixedAssets"),
                "fixed_assets_yoy": data.get("fixedAssetYoY")
                or data.get("fixedAssetsYoY"),
                "net_assets_of_plant_and_equipment": data.get(
                    "netAssetsOfPlantAndEquipment"
                ),
                "net_assets_of_plant_and_equipment_yoy": data.get(
                    "netAssetsOfPlantAndEquipmentYoY"
                ),
                "intangible_assets": data.get("intangibleAssets"),
                "intangible_assets_yoy": data.get("intangibleAssetsYoY"),
                "goodwill_intangible_assets": data.get("goodwillIntangibleAssets"),
                "goodwill_intangible_assets_yoy": data.get(
                    "goodwillIntangibleAssetsYoY"
                ),
                "other_tangible_assets": data.get("otherTangibleAssets"),
                "other_tangible_assets_yoy": data.get("otherTangibleAssetsYoY"),
                "usufruct_assetss": data.get("usufructAssetss"),
                "usufruct_assetss_yoy": data.get("usufructAssetssYoY"),
            }
        )

        # 投资相关
        formatted_data.update(
            {
                "investments": data.get("investments"),
                "investments_yoy": data.get("investmentsYoY"),
                "total_investments": data.get("totalInvestments"),
                "total_investments_yoy": data.get("totalInvestmentsYoY"),
                "total_investment_and_advances": data.get("totalInvestmentAndAdvances"),
                "total_investment_and_advances_yoy": data.get(
                    "totalInvestmentAndAdvancesYoY"
                ),
                "investment_unconsolidated_subs": data.get(
                    "investmentUnconsolidatedSubs"
                ),
                "investment_unconsolidated_subs_yoy": data.get(
                    "investmentUnconsolidatedSubsYoY"
                ),
                "lt_equity_inv": data.get("ltEquityInv"),
                "lt_equity_inv_yoy": data.get("ltEquityInvYoY"),
                "held_maturity_inv": data.get("heldMaturityInv"),
                "held_maturity_inv_yoy": data.get("heldMaturityInvYoY"),
                "investment_property": data.get("investmentProperty")
                or data.get("invProperty"),
                "investment_property_yoy": data.get("investmentPropertyYoY")
                or data.get("invPropertyYoY"),
                "other_equity_investment": data.get("otherEquityInvestment"),
                "other_equity_investment_yoy": data.get("otherEquityInvestmentYoY"),
            }
        )

        # 银行业特有资产
        formatted_data.update(
            {
                "debt_inv": data.get("dEBTINV"),
                "debt_inv_yoy": data.get("dEBTINVYoY"),
                "other_debt_inv": data.get("otherDEBTINV"),
                "other_debt_inv_yoy": data.get("otherDEBTINVYoY"),
                "purchased_resell_fina_asset": data.get("purchasedResellFinaAsset"),
                "purchased_resell_fina_asset_yoy": data.get(
                    "purchasedResellFinaAssetYoY"
                ),
                "sold_repo_fina_asset": data.get("soldRepoFinaAsset"),
                "sold_repo_fina_asset_yoy": data.get("soldRepoFinaAssetYoY"),
                "trad_fina_assets": data.get("tradFinaAssets"),
                "trad_fina_assets_yoy": data.get("tradFinaAssetsYoY"),
                "deri_fina_asset": data.get("deriFinaAsset"),
                "deri_fina_asset_yoy": data.get("deriFinaAssetYoY"),
                "loan_advance": data.get("loanAdvance"),
                "loan_advance_yoy": data.get("loanAdvanceYoY"),
                "fund_lending": data.get("fundLending"),
                "fund_lending_yoy": data.get("fundLendingYoY"),
                "deposit_in_other_bank": data.get("depositInOtherBank"),
                "deposit_in_other_bank_yoy": data.get("depositInOtherBankYoY"),
                "precious_metal": data.get("preciousMetal"),
                "precious_metal_yoy": data.get("preciousMetalYoY"),
            }
        )

        # 债务相关
        formatted_data.update(
            {
                "total_debt": data.get("totalDebt"),
                "total_debt_yoy": data.get("totalDebtYoY"),
                "long_term_debt": data.get("longTermDebt"),
                "long_term_debt_yoy": data.get("longTermDebtYoY"),
                "short_term_debt": data.get("shortTermDebt"),
                "short_term_debt_yoy": data.get("shortTermDebtYoY"),
                "bond_pay": data.get("bondPay"),
                "bond_pay_yoy": data.get("bondPayYoY"),
                "convertible_bonds_issued": data.get("convertibleBondsIssued"),
                "convertible_bonds_issued_yoy": data.get("convertibleBondsIssuedYoY"),
                "sustainable_debt": data.get("sustainableDebt"),
                "sustainable_debt_yoy": data.get("sustainableDebtYoY"),
            }
        )

        # 银行业特有负债
        formatted_data.update(
            {
                "deposit": data.get("deposit"),
                "deposit_yoy": data.get("depositYoY"),
                "total_deposits": data.get("totalDeposits"),
                "total_deposits_yoy": data.get("totalDepositsYoY"),
                "borrowing_from_cbank": data.get("borrowingFromCBank"),
                "borrowing_from_cbank_yoy": data.get("borrowingFromCBankYoY"),
                "fund_borrowing": data.get("fundBorrowing"),
                "fund_borrowing_yoy": data.get("fundBorrowingYoY"),
                "trad_fina_liab": data.get("tradFinaLiab"),
                "trad_fina_liab_yoy": data.get("tradFinaLiabYoY"),
                "deri_fina_liab": data.get("deriFinaLiab"),
                "deri_fina_liab_yoy": data.get("deriFinaLiabYoY"),
            }
        )

        # 股东权益详细
        formatted_data.update(
            {
                "share_capital": data.get("shareCapital"),
                "share_capital_yoy": data.get("shareCapitalYoY"),
                "total_share_capital": data.get("totalShareCapital"),
                "total_share_capital_yoy": data.get("totalShareCapitalYoY"),
                "retained_earnings": data.get("retainedEarning"),
                "retained_earnings_yoy": data.get("retainedEarningYoY"),
                "surplus_reserve": data.get("surplusReserve"),
                "surplus_reserve_yoy": data.get("surplusReserveYoY"),
                "total_reserves": data.get("totalReserves"),
                "total_reserves_yoy": data.get("totalReservesYoY"),
                "other_reserves": data.get("otherReserves"),
                "other_reserves_yoy": data.get("otherReservesYoY"),
                "share_premium": data.get("sharePremium"),
                "share_premium_yoy": data.get("sharePremiumYoY"),
                "capital_reserve": data.get("capitalReserve"),
                "capital_reserve_yoy": data.get("capitalReserveYoY"),
                "other_comprehensive_income": data.get("otherCompreIncome"),
                "other_comprehensive_income_yoy": data.get("otherCompreIncomeYoY"),
                "owners_equity": data.get("ownersEquity"),
                "owners_equity_yoy": data.get("ownersEquityYoY"),
                "total_sh_equity_parent_com": data.get("totalSHEquityParentCom"),
                "total_sh_equity_parent_com_yoy": data.get("totalSHEquityParentComYoY"),
                "total_common_equity": data.get("totalCommonEquity"),
                "total_common_equity_yoy": data.get("totalCommonEquityYoY"),
            }
        )

        # 少数股东权益和优先股
        formatted_data.update(
            {
                "non_controlling_interests": data.get("nonControllingInterests"),
                "non_controlling_interests_yoy": data.get("nonControllingInterestsYoY"),
                "minority_interest": data.get("minorityInterest"),
                "minority_interest_yoy": data.get("minorityInterestYoY"),
                "accumulated_minority_interest": data.get(
                    "accumulatedMinorityInterest"
                ),
                "accumulated_minority_interest_yoy": data.get(
                    "accumulatedMinorityInterestYoY"
                ),
                "preferred_stock": data.get("prefferedStock"),
                "preferred_stock_yoy": data.get("prefferedStockYoY"),
                "preferred_stock_carrying_value": data.get(
                    "preferredStockCarryingValue"
                ),
                "preferred_stock_carrying_value_yoy": data.get(
                    "preferredStockCarryingValueYoY"
                ),
                "perpetual_securities": data.get("perpetualSecurities"),
                "perpetual_securities_yoy": data.get("perpetualSecuritiesYoY"),
                "other_equity_ins": data.get("otherEquityIns"),
                "other_equity_ins_yoy": data.get("otherEquityInsYoY"),
                "non_equity_reserves": data.get("nonEquityReserves"),
                "non_equity_reserves_yoy": data.get("nonEquityReservesYoY"),
            }
        )

        # 财务比率和每股指标
        formatted_data.update(
            {
                "debt_asset_ratio": data.get("debtAssetRatio"),
                "debt_asset_ratio_yoy": data.get("debtAssetRatioYoY"),
                "current_ratio": data.get("currentRatio"),
                "current_ratio_yoy": data.get("currentRatioYoY"),
                "net_tangible_assets_per_share": data.get("netTangibleAssetsPerShare"),
                "net_tangible_assets_per_share_yoy": data.get(
                    "netTangibleAssetsPerShareYoY"
                ),
                "net_assets_per_share": data.get("netAssetsPerShare"),
                "net_assets_per_share_yoy": data.get("netAssetsPerShareYoY"),
            }
        )

        # 其他资产和负债
        formatted_data.update(
            {
                "other_current_assets": data.get("otherCurrentAssets"),
                "other_current_assets_yoy": data.get("otherCurrentAssetsYoY"),
                "other_current_liabilities": data.get("otherCurrentLiabilities"),
                "other_current_liabilities_yoy": data.get("otherCurrentLiabilitiesYoY"),
                "other_assets": data.get("otherAsset") or data.get("otherAssets"),
                "other_assets_yoy": data.get("otherAssetYoY")
                or data.get("otherAssetsYoY"),
                "other_liabilities": data.get("otherLiabilities"),
                "other_liabilities_yoy": data.get("otherLiabilitiesYoY"),
                "other_non_current_assets": data.get("otherNonCurrentAssets"),
                "other_non_current_assets_yoy": data.get("otherNonCurrentAssetsYoY"),
                "other_non_current_liab": data.get("otherNonCurrentLiab"),
                "other_non_current_liab_yoy": data.get("otherNonCurrentLiabYoY"),
            }
        )

        # 税费相关
        formatted_data.update(
            {
                "income_tax_payable": data.get("incomeTaxPayable"),
                "income_tax_payable_yoy": data.get("incomeTaxPayableYoY"),
                "tax_pay": data.get("taxPay"),
                "tax_pay_yoy": data.get("taxPayYoY"),
                "deferred_income_tax_assets": data.get("deferredIncomeTaxAssets"),
                "deferred_income_tax_assets_yoy": data.get(
                    "deferredIncomeTaxAssetsYoY"
                ),
                "deferred_tax_assets": data.get("deferredTaxAssets"),
                "deferred_tax_assets_yoy": data.get("deferredTaxAssetsYoY"),
                "deferred_tax_liabilities": data.get("deferredTaxLiabilities"),
                "deferred_tax_liabilities_yoy": data.get("deferredTaxLiabilitiesYoY"),
                "deferred_income": data.get("deferredIncome"),
                "deferred_income_yoy": data.get("deferredIncomeYoY"),
            }
        )

        # 工作资本和经营项目
        formatted_data.update(
            {
                "changes_in_work_capital": data.get("changesInWorkCapital"),
                "changes_in_work_capital_yoy": data.get("changesInWorkCapitalYoY"),
                "funds_from_operations": data.get("fundsFromOperations"),
                "funds_from_operations_yoy": data.get("fundsFromOperationsYoY"),
                "net_loans": data.get("netLoans"),
                "net_loans_yoy": data.get("netLoansYoY"),
            }
        )

        # 特殊项目和调整
        formatted_data.update(
            {
                "held_for_sale_assets": data.get("heldForSaleAssets"),
                "held_for_sale_assets_yoy": data.get("heldForSaleAssetsYoY"),
                "held_for_sale_liab": data.get("heldForSaleLiab"),
                "held_for_sale_liab_yoy": data.get("heldForSaleLiabYoY"),
                "contract_assets": data.get("contractAssets"),
                "contract_assets_yoy": data.get("contractAssetsYoY"),
                "contract_liab": data.get("contractLIAB"),
                "contract_liab_yoy": data.get("contractLIABYoY"),
                "lease_liabilities": data.get("leaseLiabilities"),
                "lease_liabilities_yoy": data.get("leaseLiabilitiesYoY"),
                "provision_for_risks_and_charges": data.get(
                    "provisionForRisksAndCharges"
                ),
                "provision_for_risks_and_charges_yoy": data.get(
                    "provisionForRisksAndChargesYoY"
                ),
                "general_risk_provision": data.get("generalRiskProvision"),
                "general_risk_provision_yoy": data.get("generalRiskProvisionYoY"),
            }
        )

        # 汇率和特殊字段
        formatted_data.update(
            {
                "rate_hkd": data.get("rateHKD"),
                "rate_usd": data.get("rateUSD"),
                "original_currency": data.get("originalCurrency"),
                "diff_conversion_fc": data.get("diffConversionFC"),
                "diff_conversion_fc_yoy": data.get("diffConversionFCYoY"),
                "fair_value_change_res": data.get("fairValueChangeRes"),
                "fair_value_change_res_yoy": data.get("fairValueChangeResYoY"),
            }
        )

        # 过滤掉None值
        return {k: v for k, v in formatted_data.items() if v is not None}

    def _format_cash_flow_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化现金流量表数据"""
        # 基础字段
        formatted_data = {
            "symbol": data.get("symbol"),
            "sec_name": data.get("secName"),
            "report_date": data.get("reportDate"),
            "report_type": data.get("reportType"),
            "currency": data.get("currency"),
            "cover_months": data.get("coverMonths"),
            "report_kind": data.get("reportKind"),
            "auditors_opinion": data.get("auditorsOpinion"),
            "opinion_name": data.get("opinionName"),
            "standard_code": data.get("standardCode"),
            "org_name": data.get("orgName"),
        }

        # 经营活动现金流
        formatted_data.update(
            {
                "net_cash_flow_operating": data.get("netCashFlowOper")
                or data.get("netOperatingCashFlow"),
                "net_cash_flow_operating_yoy": data.get("netCashFlowOperYoY")
                or data.get("netOperatingCashFlowYoY"),
                "net_cash_from_operating": data.get("netCashFromOperating"),
                "net_cash_from_operating_yoy": data.get("netCashFromOperatingYoY"),
                "cash_flow_from_operations": data.get("cashFlowFromOperations"),
                "cash_flow_from_operations_yoy": data.get("cashFlowFromOperationsYoY"),
                "sub_total_cash_in_oper": data.get("subTotalCashInOper"),
                "sub_total_cash_in_oper_yoy": data.get("subTotalCashInOperYoY"),
                "sub_total_cash_out_oper": data.get("subTotalCashOutOper"),
                "sub_total_cash_out_oper_yoy": data.get("subTotalCashOutOperYoY"),
            }
        )

        # 经营活动现金收入
        formatted_data.update(
            {
                "cash_rec_sale_goods_service": data.get("cashRecSaleGoodsService"),
                "cash_rec_sale_goods_service_yoy": data.get(
                    "cashRecSaleGoodsServiceYoY"
                ),
                "cash_rec_other_oper": data.get("cashRecOtherOper"),
                "cash_rec_other_oper_yoy": data.get("cashRecOtherOperYoY"),
                "cash_rec_other": data.get("cashRecOther"),
                "cash_rec_other_yoy": data.get("cashRecOtherYoY"),
                "cash_rec_loan": data.get("cashRecLoan"),
                "cash_rec_loan_yoy": data.get("cashRecLoanYoY"),
            }
        )

        # 经营活动现金支出
        formatted_data.update(
            {
                "cash_paid_sale_goods_service": data.get("cashPaidSaleGoodsService"),
                "cash_paid_sale_goods_service_yoy": data.get(
                    "cashPaidSaleGoodsServiceYoY"
                ),
                "cash_paid_employee": data.get("cashPaidEmployee"),
                "cash_paid_employee_yoy": data.get("cashPaidEmployeeYoY"),
                "cash_paid_other_oper": data.get("cashPaidOtherOper"),
                "cash_paid_other_oper_yoy": data.get("cashPaidOtherOperYoY"),
            }
        )

        # 投资活动现金流
        formatted_data.update(
            {
                "net_cash_flow_investing": data.get("netCashFlowInv")
                or data.get("netInvestingCashFlow"),
                "net_cash_flow_investing_yoy": data.get("netCashFlowInvYoY")
                or data.get("netInvestingCashFlowYoY"),
                "net_cash_from_investing": data.get("netCashFromInvesting"),
                "net_cash_from_investing_yoy": data.get("netCashFromInvestingYoY"),
                "subtotal_cash_in_inv": data.get("subtotalCashInInv"),
                "subtotal_cash_in_inv_yoy": data.get("subtotalCashInInvYoY"),
                "subtotal_cash_out_inv": data.get("subtotalCashOutInv"),
                "subtotal_cash_out_inv_yoy": data.get("subtotalCashOutInvYoY"),
            }
        )

        # 投资活动现金收入
        formatted_data.update(
            {
                "cash_rec_inv": data.get("cashRecInv"),
                "cash_rec_inv_yoy": data.get("cashRecInvYoY"),
                "cash_rec_divi_inv": data.get("cashRecDiviInv"),
                "cash_rec_divi_inv_yoy": data.get("cashRecDiviInvYoY"),
                "dividend_received": data.get("dividendReceived"),
                "dividend_received_yoy": data.get("dividendReceivedYoY"),
                "disposal_fixed_assets": data.get("disposalFixedAssets"),
                "disposal_fixed_assets_yoy": data.get("disposalFixedAssetsYoY"),
                "net_cash_rec_disp_fi_asset": data.get("netCashRecDispFIAsset"),
                "net_cash_rec_disp_fi_asset_yoy": data.get("netCashRecDispFIAssetYoY"),
                "net_cash_rec_disp_sub_busi": data.get("netCashRecDispSubBusi"),
                "net_cash_rec_disp_sub_busi_yoy": data.get("netCashRecDispSubBusiYoY"),
                "cash_rec_other_inv": data.get("cashRecOtherInv"),
                "cash_rec_other_inv_yoy": data.get("cashRecOtherInvYoY"),
            }
        )

        # 投资活动现金支出
        formatted_data.update(
            {
                "cash_paid_investments": data.get("cashPaidInv"),
                "cash_paid_investments_yoy": data.get("cashPaidInvYoY"),
                "additions_fixed_assets": data.get("additionsFixedAssets"),
                "additions_fixed_assets_yoy": data.get("additionsFixedAssetsYoY"),
                "capital_expenditures": data.get("capitalExpenditures"),
                "capital_expenditures_yoy": data.get("capitalExpendituresYoY"),
                "cash_paid_fi_asset": data.get("cashPaidFIAsset"),
                "cash_paid_fi_asset_yoy": data.get("cashPaidFIAssetYoY"),
                "net_cash_paid_acqu_sub_busi": data.get("netCashPaidAcquSubBusi"),
                "net_cash_paid_acqu_sub_busi_yoy": data.get(
                    "netCashPaidAcquSubBusiYoY"
                ),
                "cash_paid_other_inv": data.get("cashPaidOtherInv"),
                "cash_paid_other_inv_yoy": data.get("cashPaidOtherInvYoY"),
                "increase_investments": data.get("increaseInvestments"),
                "increase_investments_yoy": data.get("increaseInvestmentsYoY"),
                "decrease_investments": data.get("decreaseInvestments"),
                "decrease_investments_yoy": data.get("decreaseInvestmentsYoY"),
            }
        )

        # 筹资活动现金流
        formatted_data.update(
            {
                "net_cash_flow_financing": data.get("netCashFlowFina")
                or data.get("netFinancingCashFlow"),
                "net_cash_flow_financing_yoy": data.get("netCashFlowFinaYoY")
                or data.get("netFinancingCashFlowYoY"),
                "net_cash_from_financing": data.get("netCashFromFinancing"),
                "net_cash_from_financing_yoy": data.get("netCashFromFinancingYoY"),
                "sbutotal_cash_in_fina": data.get("sbutotalCashInFina"),
                "sbutotal_cash_in_fina_yoy": data.get("sbutotalCashInFinaYoY"),
                "subtotal_cash_out_fina": data.get("subtotalCashOutFina"),
                "subtotal_cash_out_fina_yoy": data.get("subtotalCashOutFinaYoY"),
            }
        )

        # 筹资活动现金收入
        formatted_data.update(
            {
                "cash_rec_fina_from_mshe_inv": data.get("cashRecFinaFromMSHEInv"),
                "cash_rec_fina_from_mshe_inv_yoy": data.get(
                    "cashRecFinaFromMSHEInvYoY"
                ),
                "cash_rec_other_fina": data.get("cashRecOtherFina"),
                "cash_rec_other_fina_yoy": data.get("cashRecOtherFinaYoY"),
                "cash_rec_inv_fina": data.get("cashREcInvFina"),
                "cash_rec_inv_fina_yoy": data.get("cashREcInvFinaYoY"),
                "new_loans": data.get("newLoans"),
                "new_loans_yoy": data.get("newLoansYoY"),
                "equity_financing": data.get("equityFinancing"),
                "equity_financing_yoy": data.get("equityFinancingYoY"),
                "debt_financing": data.get("debtFinancing"),
                "debt_financing_yoy": data.get("debtFinancingYoY"),
                "cash_from_related_parties_of_fin": data.get(
                    "cashFromRelatedPartiesOfFin"
                ),
                "cash_from_related_parties_of_fin_yoy": data.get(
                    "cashFromRelatedPartiesOfFinYoY"
                ),
            }
        )

        # 筹资活动现金支出
        formatted_data.update(
            {
                "cash_paid_divi_prof_inte": data.get("cashPaidDiviProfInte"),
                "cash_paid_divi_prof_inte_yoy": data.get("cashPaidDiviProfInteYoY"),
                "dividend_paid": data.get("dividendPaid"),
                "dividend_paid_yoy": data.get("dividendPaidYoY"),
                "cash_dividends_paid": data.get("cashDividendsPaid"),
                "cash_dividends_paid_yoy": data.get("cashDividendsPaidYoY"),
                "loans_repayment": data.get("loansRepayment"),
                "loans_repayment_yoy": data.get("loansRepaymentYoY"),
                "debt_repay": data.get("debtRepay"),
                "debt_repay_yoy": data.get("debtRepayYoY"),
                "redemption_debt_instruments": data.get("redemptionDebtInstruments"),
                "redemption_debt_instruments_yoy": data.get(
                    "redemptionDebtInstrumentsYoY"
                ),
                "change_in_capital_stock": data.get("changeInCapitalStock"),
                "change_in_capital_stock_yoy": data.get("changeInCapitalStockYoY"),
                "cash_paid_other_fina": data.get("cashPaidOtherFina"),
                "cash_paid_other_fina_yoy": data.get("cashPaidOtherFinaYoY"),
                "net_other_financing_activ_cash_flow": data.get(
                    "netOtherFinancingActivCashFlow"
                ),
                "net_other_financing_activ_cash_flow_yoy": data.get(
                    "netOtherFinancingActivCashFlowYoY"
                ),
            }
        )

        # 现金及现金等价物变动
        formatted_data.update(
            {
                "net_increase_in_cash": data.get("cashEquiNetIncr")
                or data.get("netIncreaseInCash"),
                "net_increase_in_cash_yoy": data.get("cashEquiNetIncrYoY")
                or data.get("netIncreaseInCashYoY"),
                "cash_at_beginning": data.get("cashEquiBeginning")
                or data.get("cashAtBeginningYear"),
                "cash_at_beginning_yoy": data.get("cashEquiBeginningYoY")
                or data.get("cashAtBeginningYearYoY"),
                "cash_at_end": data.get("cashEquiEnding") or data.get("cashAtEndYear"),
                "cash_at_end_yoy": data.get("cashEquiEndingYoY")
                or data.get("cashAtEndYearYoY"),
            }
        )

        # 自由现金流
        formatted_data.update(
            {
                "free_cash_flow": data.get("freeCashFlow"),
                "free_cash_flow_yoy": data.get("freeCashFlowYoY"),
            }
        )

        # 利息和税费
        formatted_data.update(
            {
                "interest_paid": data.get("interestPaid"),
                "interest_paid_yoy": data.get("interestPaidYoY"),
                "interest_received": data.get("interestReceived"),
                "interest_received_yoy": data.get("interestReceivedYoY"),
                "taxes_paid_or_refunded": data.get("taxesPaidOrRefunded"),
                "taxes_paid_or_refunded_yoy": data.get("taxesPaidOrRefundedYoY"),
                "tax_paid": data.get("taxPaid"),
                "tax_paid_yoy": data.get("taxPaidYoY"),
                "tax_refund": data.get("taxRefund"),
                "tax_refund_yoy": data.get("taxRefundYoY"),
                "paid_interest_minority": data.get("paidInterestMinority"),
                "paid_interest_minority_yoy": data.get("paidInterestMinorityYoY"),
            }
        )

        # 银行业特有现金流
        formatted_data.update(
            {
                "net_incr_lending": data.get("netIncrLending"),
                "net_incr_lending_yoy": data.get("netIncrLendingYoY"),
                "net_incr_resale_funds_oper": data.get("netIncrResaleFundsOper"),
                "net_incr_resale_funds_oper_yoy": data.get("netIncrResaleFundsOperYoY"),
                "net_incr_resale_funds_inv": data.get("netIncrResaleFundsInv"),
                "net_incr_resale_funds_inv_yoy": data.get("netIncrResaleFundsInvYoY"),
                "withdraw_loan": data.get("withdrawLoan"),
                "withdraw_loan_yoy": data.get("withdrawLoanYoY"),
                "held_fina_asset_for_trade": data.get("heldFinaAssetForTrade"),
                "held_fina_asset_for_trade_yoy": data.get("heldFinaAssetForTradeYoY"),
            }
        )

        # 其他现金流活动
        formatted_data.update(
            {
                "others_financing_activities": data.get("othersFinancingActivities"),
                "others_financing_activities_yoy": data.get(
                    "othersFinancingActivitiesYoY"
                ),
                "others_investing_activities": data.get("othersInvestingActivities"),
                "others_investing_activities_yoy": data.get(
                    "othersInvestingActivitiesYoY"
                ),
                "others_return_on_invest": data.get("othersReturnOnInvest"),
                "others_return_on_invest_yoy": data.get("othersReturnOnInvestYoY"),
                "cash_from_related_parties_of_invest": data.get(
                    "cashFromRelatedPartiesOfInvest"
                ),
                "cash_from_related_parties_of_invest_yoy": data.get(
                    "cashFromRelatedPartiesOfInvestYoY"
                ),
            }
        )

        # 汇率影响
        formatted_data.update(
            {
                "exchange_rate_effect": data.get("exchangeRateEffect"),
                "exchange_rate_effect_yoy": data.get("exchangeRateEffectYoY"),
                "effect_foreign_ex_rate": data.get("effectForeignExRate"),
                "effect_foreign_ex_rate_yoy": data.get("effectForeignExRateYoY"),
            }
        )

        # 现金流其他效应
        formatted_data.update(
            {
                "other_effect_cash_equi_ending": data.get("otherEffectCashEquiEnding"),
                "other_effect_cash_equi_ending_yoy": data.get(
                    "otherEffectCashEquiEndingYoY"
                ),
                "net_cash_flow_from_invest_and_fin": data.get(
                    "netCashFlowFromInvestAndFin"
                ),
                "net_cash_flow_from_invest_and_fin_yoy": data.get(
                    "netCashFlowFromInvestAndFinYoY"
                ),
            }
        )

        # 特殊项目和调整
        formatted_data.update(
            {
                "special_cash_in_oper": data.get("specialCashInOper"),
                "special_cash_in_oper_yoy": data.get("specialCashInOperYoY"),
                "special_cash_out_oper": data.get("specialCashOutOper"),
                "special_cash_out_oper_yoy": data.get("specialCashOutOperYoY"),
                "special_cash_in_inv": data.get("specialCashInInv"),
                "special_cash_in_inv_yoy": data.get("specialCashInInvYoY"),
                "special_cash_out_inv": data.get("specialCashOutInv"),
                "special_cash_out_inv_yoy": data.get("specialCashOutInvYoY"),
                "spcial_cash_in_fina": data.get("spcialCashInFina"),
                "spcial_cash_in_fina_yoy": data.get("spcialCashInFinaYoY"),
                "special_cash_out_fina": data.get("specialCashOutFina"),
                "special_cash_out_fina_yoy": data.get("specialCashOutFinaYoY"),
                "special_cash_equi_ending": data.get("specialCashEquiEnding"),
                "special_cash_equi_ending_yoy": data.get("specialCashEquiEndingYoY"),
            }
        )

        # 调整项目
        formatted_data.update(
            {
                "adjust_cash_in_oper": data.get("adjustCashInOper"),
                "adjust_cash_in_oper_yoy": data.get("adjustCashInOperYoY"),
                "adjust_cash_out_oper": data.get("adjustCashOutOper"),
                "adjust_cash_out_oper_yoy": data.get("adjustCashOutOperYoY"),
                "adjust_net_cash_flow_oper": data.get("adjustnetCashFlowOper"),
                "adjust_net_cash_flow_oper_yoy": data.get("adjustnetCashFlowOperYoY"),
                "adjust_cash_in_inv": data.get("adjustCashInInv"),
                "adjust_cash_in_inv_yoy": data.get("adjustCashInInvYoY"),
                "adjust_cash_out_inv": data.get("adjustCashOutInv"),
                "adjust_cash_out_inv_yoy": data.get("adjustCashOutInvYoY"),
                "adjust_cash_flow_inv": data.get("adjustCashFlowInv"),
                "adjust_cash_flow_inv_yoy": data.get("adjustCashFlowInvYoY"),
                "adjutst_cash_in_fina": data.get("adjutstCashInFina"),
                "adjutst_cash_in_fina_yoy": data.get("adjutstCashInFinaYoY"),
                "adjust_cash_out_fina": data.get("adjustCashOutFina"),
                "adjust_cash_out_fina_yoy": data.get("adjustCashOutFinaYoY"),
                "adjust_net_cash_flow_fina": data.get("adjustNetCashFlowFina"),
                "adjust_net_cash_flow_fina_yoy": data.get("adjustNetCashFlowFinaYoY"),
                "adjust_cash_equi_ending": data.get("adjustCashEquiEnding"),
                "adjust_cash_equi_ending_yoy": data.get("adjustCashEquiEndingYoY"),
                "adjust_effect_cash_equi_ending": data.get(
                    "adjustEffectCashEquiEnding"
                ),
                "adjust_effect_cash_equi_ending_yoy": data.get(
                    "adjustEffectCashEquiEndingYoY"
                ),
            }
        )

        # 其他现金流信息
        formatted_data.update(
            {
                "extraordinary_item": data.get("extraordinaryItem"),
                "extraordinary_item_yoy": data.get("extraordinaryItemYoY"),
                "miscellaneous_funds": data.get("miscellaneousFunds"),
                "miscellaneous_funds_yoy": data.get("miscellaneousFundsYoY"),
                "other_funds": data.get("otherFunds"),
                "other_funds_yoy": data.get("otherFundsYoY"),
                "other_uses": data.get("otherUses"),
                "other_uses_yoy": data.get("otherUsesYoY"),
                "funds_from_operations": data.get("fundsFromOperations"),
                "funds_from_operations_yoy": data.get("fundsFromOperationsYoY"),
                "net_income_cash_flow": data.get("netIncomeCashFlow"),
                "net_income_cash_flow_yoy": data.get("netIncomeCashFlowYoY"),
                "deferred_and_investment_tax_credit": data.get(
                    "deferredAndInvestmentTaxCredit"
                ),
                "deferred_and_investment_tax_credit_yoy": data.get(
                    "deferredAndInvestmentTaxCreditYoY"
                ),
                "depreciation_depletion_amortization": data.get(
                    "depreciationDepletionAmortization"
                ),
                "depreciation_depletion_amortization_yoy": data.get(
                    "depreciationDepletionAmortizationYoY"
                ),
                "changes_in_work_capital": data.get("changesInWorkCapital"),
                "changes_in_work_capital_yoy": data.get("changesInWorkCapitalYoY"),
                "net_change_of_debt": data.get("netChangeOfDebt"),
                "net_change_of_debt_yoy": data.get("netChangeOfDebtYoY"),
                "net_change_in_cash": data.get("netChangeInCash"),
                "net_change_in_cash_yoy": data.get("netChangeInCashYoY"),
                "net_assets_from_acquisitions": data.get("netAssetsFromAcquisitions"),
                "net_assets_from_acquisitions_yoy": data.get(
                    "netAssetsFromAcquisitionsYoY"
                ),
                "purchase_and_sale_of_investments": data.get(
                    "purchaseAndSaleOfInvestments"
                ),
                "purchase_and_sale_of_investments_yoy": data.get(
                    "purchaseAndSaleOfInvestmentsYoY"
                ),
                "sale_of_fixed_assets_and_businesses": data.get(
                    "saleOfFixedAssetsAndBusinesses"
                ),
                "sale_of_fixed_assets_and_businesses_yoy": data.get(
                    "saleOfFixedAssetsAndBusinessesYoY"
                ),
                "deposit_change": data.get("depositChange"),
                "deposit_change_yoy": data.get("depositChangeYoY"),
                "loan_settlement": data.get("loanSettlement"),
                "loan_settlement_yoy": data.get("loanSettlementYoY"),
            }
        )

        # 汇率相关 (港美股)
        formatted_data.update(
            {
                "rate_hkd": data.get("rateHKD"),
                "rate_usd": data.get("rateUSD"),
                "original_currency": data.get("originalCurrency"),
            }
        )

        # 过滤掉None值
        return {k: v for k, v in formatted_data.items() if v is not None}

    def _get_finance_key_indicators(
        self, stock_code: str, market: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取关键财务指标数据

        Args:
            stock_code: 股票代码
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            Dict: 关键财务指标数据
        """
        try:
            url = self._get_key_indicators_url(market)
            if not url:
                self.logger.error(f"不支持的关键指标市场类型: {market}")
                return None

            headers = self._get_financial_headers()
            payload = self._build_key_indicators_payload(stock_code, market)

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_key_indicators_response(data, market)

        except Exception as e:
            self.logger.error(f"获取关键财务指标失败: {str(e)}")
            return None

    def _get_key_indicators_url(self, market: str) -> Optional[str]:
        """根据市场类型获取关键财务指标API端点"""
        return self._get_financial_url(market, "key-indicator")

    def _build_key_indicators_payload(
        self, stock_code: str, market: str
    ) -> Dict[str, Any]:
        """构建关键财务指标请求payload"""
        payload = None
        if market == "us_stock":
            payload = {"symbol": stock_code, "sort": "desc"}
        else:  # hk_stock, a_stock
            payload = {
                "symbol": stock_code,
                "sort": "desc" if market == "a_stock" else None,
            }
        reportType = self._get_year_report_type(market)
        if reportType:
            payload["reportType"] = reportType
        return payload

    def _parse_key_indicators_response(
        self, data: Dict[str, Any], market: str
    ) -> Optional[Dict[str, Any]]:
        """解析关键财务指标响应数据"""
        try:
            if data.get("code") == "0" and data.get("data"):
                # 返回最新的指标数据（第一条记录）
                latest_data = data["data"][0] if data["data"] else None
                if latest_data:
                    return self._format_key_indicators_data(latest_data, market)
            return None
        except Exception as e:
            self.logger.error(f"解析关键财务指标响应失败: {str(e)}")
            return None

    def _format_key_indicators_data(
        self, data: Dict[str, Any], market: str
    ) -> Dict[str, Any]:
        """格式化关键财务指标数据"""
        if market == "hk_stock":
            return self._format_hk_key_indicators(data)
        elif market == "us_stock":
            return self._format_hk_key_indicators(data)
        elif market == "a_stock":
            return self._format_a_key_indicators(data)
        else:
            return {}

    def _format_hk_key_indicators(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化港股关键财务指标数据"""
        return {
            "symbol": data.get("symbol"),
            "report_date": data.get("reportDate"),
            "report_type": data.get("reportType"),
            "cover_months": data.get("coverMonths"),
            "currency": data.get("currency"),
            # 盈利能力指标
            "eps": data.get("eps"),
            "eps_yoy": data.get("epsYoY"),
            "net_profit": data.get("netProfit"),
            "net_profit_yoy": data.get("netProfitYoY"),
            "operating_profit": data.get("operatingProfit"),
            "operating_profit_yoy": data.get("operatingProfitYoY"),
            "operating_income": data.get("operatingIncome"),
            "operating_income_yoy": data.get("operatingIncomeYoY"),
            "net_income_ratio": data.get("netIncomeRatio"),
            "net_income_ratio_yoy": data.get("netIncomeRatioYoY"),
            "gross_profit_margin": data.get("grossProfitMargin"),
            "gross_profit_margin_yoy": data.get("grossProfitMarginYoY"),
            "return_on_equity": data.get("returnOnEquity"),
            "return_on_equity_yoy": data.get("returnOnEquityYoY"),
            "return_on_total_assets": data.get("returnOnTotalAssets"),
            "return_on_total_assets_yoy": data.get("returnOnTotalAssetsYoY"),
            # 资产负债指标
            "total_assets": data.get("totalAssets"),
            "total_assets_yoy": data.get("totalAssetsYoY"),
            "total_liabilities": data.get("totalLiabilities"),
            "total_liabilities_yoy": data.get("totalLiabilitiesYoY"),
            "debt_asset_ratio": data.get("debtAssetRatio"),
            "debt_asset_ratio_yoy": data.get("debtAssetRatioYoY"),
            "current_ratio": data.get("currentRatio"),
            "current_ratio_yoy": data.get("currentRatioYoY"),
            "quick_ratio": data.get("quickRatio"),
            "quick_ratio_yoy": data.get("quickRatioYoY"),
            # 现金流指标
            "net_cash_from_operating": data.get("netCashFromOperating"),
            "net_cash_from_operating_yoy": data.get("netCashFromOperatingYoY"),
            "net_cash_from_investing": data.get("netCashFromInvesting"),
            "net_cash_from_investing_yoy": data.get("netCashFromInvestingYoY"),
            "net_cash_from_financing": data.get("netCashFromFinancing"),
            "net_cash_from_financing_yoy": data.get("netCashFromFinancingYoY"),
            "operating_net_cash_flow_ps": data.get("operatingNetCashFlowPS"),
            "operating_net_cash_flow_ps_yoy": data.get("operatingNetCashFlowPsYoY"),
            # 每股指标
            "sales_ps": data.get("salesPS"),
            "sales_ps_yoy": data.get("salesPSYoY"),
            "net_assets_ps": data.get("netAssetsPS"),
            "net_assets_ps_yoy": data.get("netAssetsPSYoY"),
            "operating_cash_flow_ps": data.get("operatingCashFlowPS"),
            "operating_cash_flow_ps_yoy": data.get("operatingCashFlowPsYoY"),
            # 估值指标
            "pe": data.get("pe"),
            "pe_yoy": data.get("peYoY"),
            "pb": data.get("pb"),
            "pb_yoy": data.get("pbYoY"),
        }

    def _format_a_key_indicators(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化A股关键财务指标数据"""
        return {
            "symbol": data.get("symbol"),
            "report_date": data.get("reportDate"),
            "report_type": data.get("reportType"),
            "cover_months": data.get("coverMonths"),
            "currency": data.get("currency"),
            # 盈利能力指标
            "eps": data.get("eps"),
            "eps_yoy": data.get("epsYOY"),
            "basic_eps": data.get("BasicEPS"),
            "basic_eps_yoy": data.get("BasicEPSYOY"),
            "diluted_eps": data.get("dilutedeps"),
            "diluted_eps_yoy": data.get("dilutedepsYoY"),
            "eps_ttm": data.get("epsTTM"),
            "eps_ttm_yoy": data.get("epsTTMYoY"),
            "net_profit": data.get("netProfit"),
            "net_profit_yoy": data.get("netProfitYoY"),
            "operating_profit": data.get("operatingProfit"),
            "operating_profit_yoy": data.get("operatingProfitYoY"),
            "operating_income": data.get("operatingIncome"),
            "operating_income_yoy": data.get("operatingIncomeYoY"),
            "net_income_ratio": data.get("netIncomeRatio"),
            "net_income_ratio_yoy": data.get("netIncomeRatioYoY"),
            "gross_profit_margin": data.get("grossProfitMargin"),
            "gross_profit_margin_yoy": data.get("grossProfitMarginYoY"),
            "return_on_equity": data.get("returnOnEquity"),
            "return_on_equity_yoy": data.get("returnOnEquityYoY"),
            "return_on_total_assets": data.get("returnOnTotalAssets"),
            "return_on_total_assets_yoy": data.get("returnOnTotalAssetsYoY"),
            # 资产负债指标
            "total_assets": data.get("totalAssets"),  # 总资产
            "total_assets_yoy": data.get("totalAssetsYoY"),
            "total_liabilities": data.get("totalLiabilities"),
            "total_liabilities_yoy": data.get("totalLiabilitiesYoY"),
            "debt_asset_ratio": data.get("debtAssetRatio"),
            "debt_asset_ratio_yoy": data.get("debtAssetRatioYoY"),
            "current_ratio": data.get("currentRatio"),
            "current_ratio_yoy": data.get("currentRatioYoY"),
            "quick_ratio": data.get("quickRatio"),
            "quick_ratio_yoy": data.get("quickRatioYoY"),
            # 现金流指标
            "net_cash_from_operating": data.get("netCashFromOperating"),
            "net_cash_from_operating_yoy": data.get("netCashFromOperatingYoY"),
            "net_cash_from_investing": data.get("netCashFromInvesting"),
            "net_cash_from_investing_yoy": data.get("netCashFromInvestingYoY"),
            "net_cash_from_financing": data.get("netCashFromFinancing"),
            "net_cash_from_financing_yoy": data.get("netCashFromFinancingYoY"),
            "net_cash_flow_oper_ps": data.get("netCashFlowOperPS"),
            "net_cash_flow_oper_ps_yoy": data.get("netCashFlowOperPSYoY"),
            "net_cash_flow_ps": data.get("netCashFlowPS"),
            "net_cash_flow_ps_yoy": data.get("netCashFlowPSYoY"),
            "cash_flow_oper_ps": data.get("cashFlowOperPS"),
            "cash_flow_oper_ps_yoy": data.get("cashFlowOperPSYoY"),
            # 每股指标
            "net_assets_ps": data.get("netAssetsPS"),
            "net_assets_ps_yoy": data.get("netAssetsPSYoY"),
            "oper_income_ps": data.get("operIncomePS"),
            "oper_income_ps_yoy": data.get("OperIncomePSYoY"),
            "retained_earning_ps": data.get("retainedEarningPS"),
            "retained_earning_ps_yoy": data.get("retainedEarningPSYoY"),
            "capital_reserve_ps": data.get("capitalReservePS"),
            "capital_reserve_ps_yoy": data.get("capitalReservePSYoY"),
            "shfcf_ps": data.get("shfcfPS"),
            "shfcf_ps_yoy": data.get("shfcfPSYoY"),
            "ebit_ps": data.get("ebitPS"),
            "ebit_ps_yoy": data.get("ebitPSYoY"),
            # 估值指标
            "pe": data.get("pe"),
            "pe_yoy": data.get("peYoY"),
            "pb": data.get("pb"),
            "pb_yoy": data.get("pbYoY"),
        }

    def get_valuation_metrics(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取估值指标数据

        Args:
            stock_code: 股票代码
            market: 市场类型

        Returns:
            Dict: 估值指标数据，包含PE、PB、PS、PEG等
        """
        # TODO: 实现FIU API获取估值指标的逻辑
        self.logger.debug(f"FIU获取估值指标: {stock_code}, 市场: {market}")
        try:
            # 验证市场类型
            if market not in ["a_stock", "hk_stock", "us_stock"]:
                self.logger.warning(f"不支持的市场类型: {market}")
                return {}

            result = {}
            auth_error_count = 0

            # 获取关键财务指标数据
            key_indicators = self._get_finance_key_indicators(stock_code, market)
            if key_indicators:
                result["key_indicators"] = key_indicators
            elif self._is_auth_error():
                auth_error_count += 1

            # 如果多个请求都返回认证错误，给出明确提示
            if auth_error_count >= 2 and not result:
                self.logger.warning(
                    f"检测到认证错误，请检查API token是否已过期: {stock_code}"
                )
                result["error"] = "API认证失败，请检查token配置"

            return result
        except Exception as e:
            self.logger.error(
                f"获取关键指标失败: {stock_code}, {market}, 错误: {str(e)}"
            )
            return {}

    def get_major_shareholders(
        self, stock_code: str, market: str
    ) -> List[Dict[str, Any]]:
        """
        获取主要股东数据

        Args:
            stock_code: 股票代码 (如: 00700.hk, AAPL.us, 600519.sh)
            market: 市场类型 (hk_stock, us_stock, a_stock)

        Returns:
            List[Dict]: 主要股东数据列表，包含股东姓名、持股数量、持股比例等信息
        """
        try:
            self.logger.debug(f"FIU获取主要股东数据: {stock_code}, 市场: {market}")

            # 验证市场类型
            if market not in ["a_stock", "hk_stock", "us_stock"]:
                self.logger.warning(f"不支持的市场类型: {market}")
                return []

            # 获取主要股东数据
            shareholders_data = self._get_major_shareholders_data(stock_code, market)
            if shareholders_data:
                return self._format_major_shareholders(shareholders_data, market)

            return []

        except Exception as e:
            self.logger.error(
                f"获取主要股东数据失败: {stock_code}, {market}, 错误: {str(e)}"
            )
            return []

    def _get_major_shareholders_data(
        self, stock_code: str, market: str
    ) -> Optional[List[Dict[str, Any]]]:
        """获取主要股东原始数据"""
        try:
            url = self._get_major_shareholders_url(market)
            if not url:
                return None

            headers = self._get_stock_info_headers()
            payload = self._build_major_shareholders_payload(stock_code, market)

            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=15
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                return data["data"]

            return None

        except Exception as e:
            self.logger.error(f"获取主要股东原始数据失败: {str(e)}")
            return None

    def _get_major_shareholders_url(self, market: str) -> Optional[str]:
        """获取主要股东API URL"""
        urls = {
            "hk_stock": "https://globaldata1-ali.szfuit.com/api/hk/f10/summary/major-shareholders",
            "us_stock": "https://globaldata1-ali.szfuit.com/api/us/f10/summary/major-shareholders",
            "a_stock": "https://globaldata1-ali.szfuit.com/api/hs/f10/summary/topten-holder-stastatistics",
        }
        return urls.get(market)

    def _build_major_shareholders_payload(
        self, stock_code: str, market: str
    ) -> Dict[str, Any]:
        """构建主要股东请求payload"""
        if market in ["hk_stock", "us_stock"]:
            return {"symbol": stock_code, "sort": "desc"}
        elif market == "a_stock":
            return {"symbol": stock_code, "sort": "desc"}
        else:
            return {}

    def _format_major_shareholders(
        self, data_list: List[Dict[str, Any]], market: str
    ) -> List[Dict[str, Any]]:
        """格式化主要股东数据为统一格式"""
        formatted_shareholders = []

        for item in data_list:
            if market == "hk_stock":
                shareholder = {
                    "symbol": item.get("symbol"),
                    "holder_name": item.get("holderName"),
                    "holder_name_en": item.get("holderNameEn"),
                    "holder_type": item.get("holderType"),
                    "holding_number": item.get("holdingNumber"),
                    "holding_ratio": item.get("holdingRatio"),
                    "change_number": item.get("changeNumber"),
                    "report_date": item.get("reportDate"),
                    "data_source": item.get("dataSource"),
                    "holder_seccode": item.get("holderSeccode"),
                }
            elif market == "us_stock":
                shareholder = {
                    "symbol": item.get("symbol"),
                    "holder_name": item.get("holderName"),
                    "holder_type": item.get("holderType"),
                    "holding_number_ads": item.get("holdingNumber_ADS"),
                    "holding_number_os": item.get("holdingNumber_OS"),
                    "holding_ratio": item.get("holdingRatio"),
                    "change_number_ads": item.get("changeNumber_ADS"),
                    "change_number_os": item.get("changeNumber_OS"),
                    "change_ratio_ads": item.get("changeRatio_ADS"),
                    "change_ratio_os": item.get("changeRatio_OS"),
                    "report_date": item.get("reportDate"),
                    "pub_date": item.get("pubDate"),
                }
            elif market == "a_stock":
                shareholder = {
                    "symbol": item.get("symbol"),
                    "holder_name": item.get("holderName"),
                    "holder_type": item.get("type"),  # A股使用type字段表示股东类型
                    "holding_number": item.get("holdingNumber"),
                    "holding_ratio": item.get("holdingRatio"),
                    "holding_number_change": item.get("holdingNumberChange"),
                    "holding_ratio_change": item.get("holdingRatioChange"),
                    "report_date": item.get("reportDate"),
                }
            else:
                continue

            # 过滤掉None值
            shareholder = {k: v for k, v in shareholder.items() if v is not None}
            formatted_shareholders.append(shareholder)

        return formatted_shareholders

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            bool: True if available, False otherwise
        """
        if self._available:
            return True
        try:
            # 尝试获取A股财务数据来测试连接
            test_result = self.get_financial_indicators("000001.sz", "a_stock")
            self._available = bool(test_result)
        except Exception as e:
            self.logger.warning(f"FIU财务数据API连接检查失败: {str(e)}")
            self._available = False
        return self._available
