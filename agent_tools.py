import json
import requests
from langchain.tools import tool

@tool
def get_current_weather(city:str) -> str:
    """查询指定城市的当前天气。

    当用户询问某个城市的实时天气、温度、湿度、
    风速、是否下雨等信息时，调用此工具。

    Args:
        city: 需要查询天气的城市名称，例如北京、上海、合肥。
    """
    try:
        # 根据城市名查询经纬度
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"

        geo_response = requests.get(
            geo_url,
            params={
                "name": city,
                "count": 1,
                "language": "zh",
                "format": "json"
            },
            timeout=10
        )
        geo_response.raise_for_status()

        locations = geo_response.json().get("results", [])

        if not locations:
            return json.dumps({
                "error": f"未找到城市:{city}"
            }, ensure_ascii=False)

        location = locations[0]

        latitude = location["latitude"]
        longitude = location["longitude"]


        # 调用天气 API
        weather_url = "https://api.open-meteo.com/v1/forecast"

        weather_response = requests.get(
            weather_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "weather_code",
                    "wind_speed_10m",
                ],        
                "timezone": "auto"
            },
            timeout=10
        )
        weather_response.raise_for_status()

        weather_data = weather_response.json()
        current = weather_data["current"]

        # 整理数据
        result = {
            "city": location["name"],
            "region": location.get("admin1", ""),
            "country": location.get("country", ""),
            "observation_time": current["time"],
            "timezone": weather_data.get("timezone"),
            "temperature": current["temperature_2m"],
            "temperature_unit": "°C",
            "humidity": current["relative_humidity_2m"],
            "humidity_unit": "%",
            "feels_like": current["apparent_temperature"],
            "precipitation": current["precipitation"],
            "precipitation_unit": "mm",
            "weather_code": current["weather_code"],
            "wind_speed": current["wind_speed_10m"],
            "wind_speed_unit": "km/h",
            "source": "Open-Meteo"
        }

        return json.dumps(result, ensure_ascii=False)

    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        return json.dumps({
            "error": f"天气查询失败： {str(e)}"
        }, ensure_ascii=False)



if __name__ == "__main__":
    # 测试
    result = get_current_weather.invoke({"city": "成都"})
    print(result)