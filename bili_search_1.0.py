import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import csv
import time
import threading
from functools import partial


class BiliMarketAPI:
    SEARCH_URL = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Referer": "https://mall.bilibili.com/neul-next/index.html",
        "Content-Type": "application/json",
        "Origin": "https://mall.bilibili.com"
    }

    CATEGORY_MAP = {
        "手办": "2312",
        "模型": "2066",
        "周边": "2331",
        "3C": "2273",
        "福袋": "fudai_cate_id"
    }

    SORT_MAP = {
        "默认排序": "TIME_DESC",
        "价格升序": "PRICE_ASC",
        "价格降序": "PRICE_DESC"
    }


class BiliSpider:
    def __init__(self):
        self.running = False
        self.results = []
        self.next_id = None
        self.lock = threading.Lock()

    def start_search(self, params, progress_callback):
        self.running = True
        self.results = []
        self.next_id = None

        try:
            while self.running and len(self.results) < params["max_results"]:
                payload = self._build_payload(params)
                response = self._make_request(payload, params["cookie"])

                if not self._validate_response(response, progress_callback):
                    break

                data = self._parse_response(response)
                if not data:
                    break

                if not self._process_data(data, params, progress_callback):
                    break

                time.sleep(params["interval"])

        except Exception as e:
            progress_callback(f"发生错误: {str(e)}")
            self.running = False
        finally:
            self.running = False

        return self.results

    def _build_payload(self, params):
        return {
            "categoryFilter": params["category"],
            "priceFilters": [self._format_price(params)],
            "discountFilters": [params["discount"]],
            "nextId": self.next_id,
            "sortType": params["sort_type"]
        }

    def _format_price(self, params):
        try:
            min_price = int(float(params["min_price"]) * 100)
            max_price = int(float(params["max_price"]) * 100)
            return f"{min_price}-{max_price}"
        except ValueError:
            raise ValueError("价格参数无效，请输入数字")

    def _make_request(self, payload, cookie):
        try:
            headers = BiliMarketAPI.HEADERS.copy()
            headers["Cookie"] = cookie
            return requests.post(
                BiliMarketAPI.SEARCH_URL,
                headers=headers,
                json=payload,
                timeout=15
            )
        except Exception as e:
            raise Exception(f"请求失败: {str(e)}")

    def _validate_response(self, response, callback):
        if not response:
            callback("服务器无响应")
            return False
        if response.status_code == 412:
            callback("触发反爬机制，请更换IP或Cookie")
            return False
        if response.status_code != 200:
            callback(f"HTTP错误码: {response.status_code}")
            return False
        return True

    def _parse_response(self, response):
        try:
            data = response.json()
            if data.get("code") != 0:
                raise Exception(f"API错误: {data.get('message')}")
            return data
        except json.JSONDecodeError:
            raise Exception("无效的JSON响应")

    def _process_data(self, data, params, callback):
        items = data.get("data", {}).get("data", [])
        self.next_id = data.get("data", {}).get("nextId")

        with self.lock:
            new_items = 0
            for item in items:
                try:
                    if self._match_conditions(item, params):
                        self._add_item(item)
                        new_items += 1
                        callback(f"找到：{item['c2cItemsName']} | 价格：{self._parse_price(item['showPrice'])}元")
                except Exception as e:
                    callback(f"数据处理错误: {str(e)}")

            if new_items == 0:
                callback("本页未找到符合条件的结果")

            if not self.next_id:
                callback("已到达最后一页")
                return False

            return True

    def _parse_price(self, price):
        """统一处理价格字段类型"""
        try:
            return float(price)
        except (TypeError, ValueError):
            return 0.0

    def _match_conditions(self, item, params):
        name = item.get("c2cItemsName", "")
        price = self._parse_price(item.get("showPrice"))
        min_price = float(params["min_price"])
        max_price = float(params["max_price"])

        # 价格验证
        if not (min_price <= price <= max_price):
            return False

        # 关键词匹配
        keywords = [k.strip() for k in params["keywords"] if k.strip()]
        if keywords and not any(k.lower() in name.lower() for k in keywords):
            return False

        # 折扣验证
        if params["discount"]:
            try:
                discount_range = list(map(int, params["discount"].split("-")))
                original_price = self._parse_price(item.get("originalPrice"))
                if original_price <= 0:
                    return False
                actual_discount = int((price / original_price) * 100)
                if not (discount_range[0] <= actual_discount <= discount_range[1]):
                    return False
            except Exception as e:
                print(f"折扣计算错误: {str(e)}")
                return False

        return True

    def _add_item(self, item):
        """确保数据类型正确"""
        self.results.append({
            "name": str(item.get("c2cItemsName", "未知商品")),
            "price": self._parse_price(item.get("showPrice")),
            "link": f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={item.get('c2cItemsId', '')}"
        })


class SpiderGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("B站市集搜索器 v1.0")
        self.window.geometry("800x650")
        self._setup_ui()
        self.spider = BiliSpider()
        self.export_path = ""
        self.search_thread = None

    def _setup_ui(self):
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Cookie输入区
        cookie_frame = ttk.LabelFrame(main_frame, text="Cookie设置 (必需)")
        cookie_frame.pack(fill=tk.X, pady=5)
        self.cookie_text = scrolledtext.ScrolledText(cookie_frame, height=4)
        self.cookie_text.pack(fill=tk.X, padx=5, pady=5)

        # 搜索条件区
        search_frame = ttk.LabelFrame(main_frame, text="搜索条件")
        search_frame.pack(fill=tk.X, pady=5)

        # 分类选择
        ttk.Label(search_frame, text="商品分类:").grid(row=0, column=0, padx=5, sticky="w")
        self.category_var = tk.StringVar()
        category_cb = ttk.Combobox(search_frame, textvariable=self.category_var,
                                   values=list(BiliMarketAPI.CATEGORY_MAP.keys()))
        category_cb.grid(row=0, column=1, padx=5, sticky="ew")
        category_cb.current(0)

        # 关键词输入
        ttk.Label(search_frame, text="关键词:").grid(row=1, column=0, padx=5, sticky="w")
        self.keyword1 = ttk.Entry(search_frame)
        self.keyword1.grid(row=1, column=1, padx=5, sticky="ew")
        self.keyword2 = ttk.Entry(search_frame)
        self.keyword2.grid(row=1, column=2, padx=5, sticky="ew")

        # 价格区间
        ttk.Label(search_frame, text="价格区间:").grid(row=2, column=0, padx=5, sticky="w")
        self.min_price = ttk.Entry(search_frame, width=10, validate="key")
        self.min_price.config(validatecommand=(self.min_price.register(self._validate_float), "%P"))
        self.min_price.grid(row=2, column=1, padx=5, sticky="w")
        ttk.Label(search_frame, text="-").grid(row=2, column=2)
        self.max_price = ttk.Entry(search_frame, width=10, validate="key")
        self.max_price.config(validatecommand=(self.max_price.register(self._validate_float), "%P"))
        self.max_price.grid(row=2, column=3, padx=5, sticky="w")

        # 折扣筛选
        ttk.Label(search_frame, text="折扣范围:").grid(row=3, column=0, padx=5, sticky="w")
        self.discount_var = tk.StringVar()
        discount_cb = ttk.Combobox(search_frame, textvariable=self.discount_var,
                                   values=["默认全选", "3折以下", "3-5折", "5-7折", "7折以上"])
        discount_cb.grid(row=3, column=1, padx=5, sticky="ew")
        discount_cb.current(0)

        # 排序方式
        ttk.Label(search_frame, text="排序方式:").grid(row=4, column=0, padx=5, sticky="w")
        self.sort_var = tk.StringVar(value="默认排序")
        sort_cb = ttk.Combobox(search_frame, textvariable=self.sort_var,
                               values=list(BiliMarketAPI.SORT_MAP.keys()))
        sort_cb.grid(row=4, column=1, padx=5, sticky="ew")

        # 控制区
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=5)
        ttk.Button(control_frame, text="开始搜索", command=self.start_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="停止搜索", command=self.stop_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="选择路径", command=self.set_save_path).pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar()
        ttk.Label(control_frame, textvariable=self.status_var).pack(side=tk.RIGHT, padx=5)

        # 日志区
        log_frame = ttk.LabelFrame(main_frame, text="实时日志")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _validate_float(self, value):
        """验证浮点数输入"""
        if value == "":
            return True
        try:
            float(value)
            return True
        except ValueError:
            return False

    def set_save_path(self):
        path = filedialog.askdirectory()
        if path:
            self.export_path = path
            self.status_var.set(f"保存路径: {path}")

    def start_search(self):
        if not self._validate_inputs():
            return

        params = self._build_search_params()
        if not params:
            return

        self.search_thread = threading.Thread(target=self.run_search, args=(params,))
        self.search_thread.daemon = True
        self.search_thread.start()

    def _build_search_params(self):
        """构建请求参数并验证类型"""
        try:
            min_price = float(self.min_price.get() or 0)
            max_price = float(self.max_price.get() or 9999)
            if min_price > max_price:
                raise ValueError("最小价格不能大于最大价格")
            if min_price < 0 or max_price < 0:
                raise ValueError("价格不能为负数")

            return {
                "category": BiliMarketAPI.CATEGORY_MAP[self.category_var.get()],
                "min_price": min_price,
                "max_price": max_price,
                "keywords": [self.keyword1.get(), self.keyword2.get()],
                "sort_type": BiliMarketAPI.SORT_MAP[self.sort_var.get()],
                "discount": self._get_discount(),
                "cookie": self.cookie_text.get("1.0", tk.END).strip(),
                "interval": 2,
                "max_results": 3000
            }
        except ValueError as e:
            messagebox.showwarning("输入错误", str(e))
            return None

    def _get_discount(self):
        discount_map = {
            "默认全选": "",
            "3折以下": "0-30",
            "3-5折": "30-50",
            "5-7折": "50-70",
            "7折以上": "70-100"
        }
        return discount_map[self.discount_var.get()]

    def _validate_inputs(self):
        """增强输入验证"""
        if not self.cookie_text.get("1.0", tk.END).strip():
            messagebox.showwarning("警告", "必须输入有效Cookie！")
            return False

        if not self.export_path:
            messagebox.showwarning("警告", "请先选择保存路径！")
            return False

        return True

    def run_search(self, params):
        self._log("搜索启动...")
        results = self.spider.start_search(params, self._log)

        if results:
            self._save_results(results)
            self._log(f"成功保存 {len(results)} 条结果")
            messagebox.showinfo("完成", f"搜索完成，共找到 {len(results)} 条结果")
        else:
            self._log("搜索完成，未找到结果")
            messagebox.showinfo("完成", "搜索完成，未找到符合条件的结果")

    def stop_search(self):
        if self.spider.running:
            self.spider.running = False
            self._log("正在停止搜索...")

    def _log(self, message):
        self.log_area.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.log_area.see(tk.END)
        self.window.update()

    def _save_results(self, results):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"bili_results_{timestamp}"

        # 保存CSV
        csv_path = f"{self.export_path}/{base_name}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["name", "price", "link"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        # 保存TXT
        txt_path = f"{self.export_path}/{base_name}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            for item in results:
                f.write(f"名称：{item['name']}\n价格：{item['price']}元\n链接：{item['link']}\n\n")

        self._log(f"结果已保存至：\n{csv_path}\n{txt_path}")


if __name__ == "__main__":
    app = SpiderGUI()
    app.window.mainloop()