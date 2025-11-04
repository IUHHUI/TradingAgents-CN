"""
Base Data Source Classes
基础数据源抽象类 - 定义统一的数据源接口
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import pandas as pd
from datetime import datetime


class DataSourceError(Exception):
    """数据源异常类"""
    pass


class BasePriceDataSource(ABC):
    """价格数据源基类"""
    
    @abstractmethod
    def get_stock_data(self, stock_code: str, market: str, period: str = '1y') -> Optional[pd.DataFrame]:
        """
        获取股票价格数据
        
        Args:
            stock_code: 股票代码
            market: 市场类型 (a_stock, hk_stock, us_stock)
            period: 时间周期
            
        Returns:
            DataFrame: 价格数据，包含 ['date', 'open', 'high', 'low', 'close', 'volume'] 列
        """
        pass
    
    @abstractmethod
    def get_realtime_price(self, stock_code: str, market: str) -> Optional[Dict[str, Any]]:
        """
        获取实时价格数据
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            
        Returns:
            Dict: 实时价格信息
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass


class BaseFundamentalDataSource(ABC):
    """基本面数据源基类"""
    
    @abstractmethod
    def get_stock_info(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取股票基本信息
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            
        Returns:
            Dict: 股票基本信息
        """
        pass
    
    @abstractmethod
    def get_financial_indicators(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取财务指标
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            
        Returns:
            Dict: 财务指标数据
        """
        pass
    
    @abstractmethod
    def get_valuation_metrics(self, stock_code: str, market: str) -> Dict[str, Any]:
        """
        获取估值指标
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            
        Returns:
            Dict: 估值指标数据
        """
        pass
    
    @abstractmethod
    def get_major_shareholders(self, stock_code: str, market: str) -> List[Dict[str, Any]]:
        """
        获取主要股东数据
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            
        Returns:
            List[Dict]: 主要股东数据列表
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass


class BaseNewsDataSource(ABC):
    """新闻数据源基类"""
    
    @abstractmethod
    def get_stock_news(self, stock_code: str, market: str, days: int = 15) -> List[Dict[str, Any]]:
        """
        获取股票相关新闻
        
        Args:
            stock_code: 股票代码
            market: 市场类型
            days: 天数
            
        Returns:
            List[Dict]: 新闻列表，每条新闻包含 title, content, time, sentiment 等字段
        """
        pass
    
    @abstractmethod
    def get_market_news(self, market: str, days: int = 7) -> List[Dict[str, Any]]:
        """
        获取市场新闻
        
        Args:
            market: 市场类型
            days: 天数
            
        Returns:
            List[Dict]: 市场新闻列表
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass


class BaseDataSourceRegistry:
    """数据源注册表基类"""
    
    def __init__(self):
        self.price_sources: List[BasePriceDataSource] = []
        self.fundamental_sources: List[BaseFundamentalDataSource] = []
        self.news_sources: List[BaseNewsDataSource] = []
    
    def register_price_source(self, source: BasePriceDataSource):
        """注册价格数据源"""
        self.price_sources.append(source)
    
    def register_fundamental_source(self, source: BaseFundamentalDataSource):
        """注册基本面数据源"""
        self.fundamental_sources.append(source)
    
    def register_news_source(self, source: BaseNewsDataSource):
        """注册新闻数据源"""
        self.news_sources.append(source)
    
    def get_available_price_sources(self) -> List[BasePriceDataSource]:
        """获取可用的价格数据源"""
        return [source for source in self.price_sources if source.is_available()]
    
    def get_available_fundamental_sources(self) -> List[BaseFundamentalDataSource]:
        """获取可用的基本面数据源"""
        return [source for source in self.fundamental_sources if source.is_available()]
    
    def get_available_news_sources(self) -> List[BaseNewsDataSource]:
        """获取可用的新闻数据源"""
        return [source for source in self.news_sources if source.is_available()]