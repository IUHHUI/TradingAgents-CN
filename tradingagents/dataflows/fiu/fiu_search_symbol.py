import http.client
import json
import ssl
import os


def search_list(key: str) -> list[dict]:
    url = "https://mdci.szfiu.com/h5/common/v1/stock/search"
    search_key = key
    if key.find(".") > 0:
        search_key = key[0 : key.find(".")]
    rr = _search(url=url, key=search_key)
    if not rr["success"]:
        return []
    return rr["text"]


def search_one(key: str) -> dict:
    """
    搜尋股票信息:个股,OTC
    """
    url = "https://mdci.szfiu.com/h5/common/v1/stock/search"
    search_key = key
    if key.find(".") > 0:
        search_key = key[0 : key.find(".")]
    rr = _search(url=url, key=search_key)
    if not rr["success"]:
        return {}
    if len(rr["text"]) == 1:
        return rr["text"][0]

    minIndex = 100
    match_obj = rr["text"][0]
    for info in rr["text"]:
        ms = str(info["marketSymbol"])
        mi = ms.find(search_key)
        if mi == 0:
            return info
        if mi > 0 and mi < minIndex:
            minIndex = mi
            match_obj = info
    return match_obj


def _search(url: str, key: str) -> dict:
    """通过关键字检索证券代码."""
    host = url.split("/")[2]
    headers = {
        "Content-Type": "application/json",
    }

    if os.getenv("SEARCH_TOKEN"):
        headers["Authorization"] = os.getenv("SEARCH_TOKEN")

    conn = http.client.HTTPSConnection(
        host=host, context=ssl._create_unverified_context()
    )
    payload = json.dumps({"key": key})
    conn.request("POST", url=url, body=payload, headers=headers)
    res = conn.getresponse()
    resData = res.read()
    dataStr = resData.decode("utf-8")
    data = json.loads(dataStr)
    """ 响应内容
    {
    "code": 200,
    "success": true,
    "text": [
            [
            "00700", //symbol
            "00700.hk", //marketSymbol
            1, //市场编码标准
            1, //证券主类型编码
            null, //权证衍生品子类编码
            "腾讯控股",
            "騰訊控股",
            "TENCENT"
            ],
        ]
    }
    """
    result = {}
    result["code"] = data["code"]
    if data["success"] and len(data["data"]) > 0:
        dd = []
        for info in data["data"]:
            # 只返回 个股 and OTC
            if info[3] == 1 or info[3] == 2 or info[3] == 12:
                dd.append(to_symbol_object(info))
        result["success"] = True if len(dd) > 0 else False
        result["text"] = dd
    else:
        result["success"] = False
        result["text"] = []
    return result


def to_symbol_object(symbol_data: list) -> str:
    """[
        "00700", //symbol
        "00700.hk", //marketSymbol
        1, //市场编码标准
        1, //证券主类型编码
        null, //权证衍生品子类编码
        "腾讯控股",
        "騰訊控股",
        "TENCENT"
    ]
    """
    symbol = str(symbol_data[0])
    marketSymbol = str(symbol_data[1])
    funcCallSymbol = marketSymbol + "." + str(symbol_data[3])
    cnName = symbol_data[5]
    enName = symbol_data[7]
    typeStr = str(symbol_data[3])

    market = "hk"
    marketZone = "hk"
    marketSymbolLower = marketSymbol.lower()
    if marketSymbolLower.endswith("hk"):
        market = "hk"
        marketZone = "hk"
    elif marketSymbolLower.endswith("us"):
        market = "us"
        marketZone = "us"
    elif marketSymbolLower.endswith("jp"):
        market = "jp"
        marketZone = "jp"
    elif marketSymbolLower.endswith("sh"):
        market = "hs"
        marketZone = "hs"
    elif marketSymbolLower.endswith("sz"):
        market = "hs"
        marketZone = "hs"
    return {
        "symbol": symbol,
        "marketSymbol": marketSymbol,
        "funcCallSymbol": funcCallSymbol,
        "chineseName": cnName,
        "englishName": enName,
        "market": market,
        "marketZone": marketZone,
        "marketSymbol": marketSymbol,
        "type": typeStr,
    }


def get_market_text(symbol_object: dict) -> str:
    if symbol_object:
        if symbol_object["type"] == "12":
            return "us_otc"
        if symbol_object["type"] == "1":
            if symbol_object["market"] == "hk":
                return "hk_stock"
            elif symbol_object["market"] == "us":
                return "us_stock"
            elif symbol_object["market"] == "hs":
                return "a_stock"
            elif symbol_object["market"] == "jp":
                return "jp_stock"
    return ""


def main(key: str) -> dict:
    """通过关键字检索证券代码."""
    if not key:
        return {}
    return search_one(key=key)


if __name__ == "__main__":
    print(main(key="0700"))
    print(main(key="00700"))
    print(main(key="00700.hk"))
    # Cocrystal Pharma Inc
    print(main(key="Cocrystal"))
    print(main(key="cocrystal"))
    print(main(key="tcl科技"))
    print(main(key="7203.jp"))
    print(main(key="7203"))
    print(main(key="TQQQ"))
