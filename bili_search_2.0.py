import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import csv
import time
import threading


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

    PRICE_RANGES = {
        "全部": "",
        "20以下": "0-2000",
        "20-30": "2000-3000",
        "30-50": "3000-5000",
        "50-100": "5000-10000",
        "100-200": "10000-20000",
        "200以上": "20000-99999999"
    }


class BiliSpider:
    def __init__(self):
        self.running = False
        self.results = []
        self.next_id = None
        self.lock = threading.Lock()
        self.retry_count = 0

    def start_search(self, params, progress_callback):
        self.running = True
        self.results = []
        self.next_id = None

        try:
            while self.running and len(self.results) < params["max_results"]:
                payload = self._build_payload(params)
                progress_callback(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")
                response = self._make_request(payload, params["cookie"], progress_callback)

                if not self._validate_response(response, progress_callback):
                    break

                data = self._parse_response(response, progress_callback)
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
            "priceFilters": [params["price_range"]] if params["price_range"] else [],
            "discountFilters": [params["discount"]] if params["discount"] else [],
            "nextId": self.next_id,
            "sortType": params["sort_type"],
            "keyword": " ".join([kw for kw in params["keywords"] if kw.strip()])
        }

    def _make_request(self, payload, cookie, progress_callback):
        max_retries = 100
        retry_delay = 5
        for attempt in range(max_retries):
            if not self.running:
                raise Exception("用户停止搜索")
            try:
                headers = BiliMarketAPI.HEADERS.copy()
                headers["Cookie"] = cookie
                response = requests.post(
                    BiliMarketAPI.SEARCH_URL,
                    headers=headers,
                    json=payload,
                    timeout=15
                )
                return response
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                self.retry_count += 1
                error_type = "连接超时" if isinstance(e, requests.exceptions.Timeout) else "连接错误"
                progress_callback(f"{error_type}，正在进行第{self.retry_count}次重试", retry=True)
                time.sleep(retry_delay)
            except Exception as e:
                raise Exception(f"请求异常: {str(e)}")

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

    def _parse_response(self, response, callback):
        try:
            data = response.json()
            if data.get("code") != 0:
                callback(f"API错误: {data.get('message')}")
                return None
            return data
        except json.JSONDecodeError:
            callback("无效的JSON响应")
            return None

    def _process_data(self, data, params, callback):
        items = data.get("data", {}).get("data", [])
        if items is None:
            callback("API返回的商品列表为None")
            return False

        callback(f"本页返回商品数: {len(items)}")
        with self.lock:
            new_items = 0
            for item in items:
                try:
                    if self._match_conditions(item, params):
                        self._add_item(item)
                        new_items += 1
                        callback(f"找到：{item['c2cItemsName']} | 价格：{self._parse_price(item.get('showPrice', 0))}元")
                    else:
                        callback(f"过滤：{item['c2cItemsName']} 未通过条件")
                except Exception as e:
                    callback(f"数据处理错误: {str(e)}")

            if new_items == 0:
                callback("本页未找到符合条件的结果")

            self.next_id = data.get("data", {}).get("nextId")
            if not self.next_id:
                callback("已到达最后一页")
                return False

            return True

    def _parse_price(self, price):
        try:
            return float(price)
        except (TypeError, ValueError):
            return 0.0

    def _match_conditions(self, item, params):
        name = item.get("c2cItemsName", "").lower()
        keywords = [k.strip().lower() for k in params["keywords"] if k.strip()]
        if keywords and not any(k in name for k in keywords):
            return False

        if params["discount"] and params["discount"].strip():
            try:
                discount_range = list(map(int, params["discount"].split("-")))
                original_price = item.get("originalPrice")
                show_price = item.get("showPrice")
                if original_price is None or show_price is None:
                    return False
                original_price = self._parse_price(original_price)
                show_price = self._parse_price(show_price)
                if original_price <= 0:
                    return False
                actual_discount = int((show_price / original_price) * 100)
                if not (discount_range[0] <= actual_discount <= discount_range[1]):
                    return False
            except Exception:
                return False

        return True

    def _add_item(self, item):
        self.results.append({
            "name": str(item.get("c2cItemsName", "未知商品")),
            "price": self._parse_price(item.get("showPrice")),
            "link": f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={item.get('c2cItemsId', '')}"
        })


class SpiderGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("B站市集搜索器 v2.0")
        self.window.geometry("800x650")
        self._setup_ui()
        self.spider = BiliSpider()
        self.export_path = ""
        self.search_thread = None

    def _setup_ui(self):
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        cookie_frame = ttk.LabelFrame(main_frame, text="Cookie设置 (必需)")
        cookie_frame.pack(fill=tk.X, pady=5)
        self.cookie_text = scrolledtext.ScrolledText(cookie_frame, height=4)
        self.cookie_text.pack(fill=tk.X, padx=5, pady=5)

        search_frame = ttk.LabelFrame(main_frame, text="搜索条件")
        search_frame.pack(fill=tk.X, pady=5)

        ttk.Label(search_frame, text="商品分类:").grid(row=0, column=0, padx=5, sticky="w")
        self.category_var = tk.StringVar()
        category_cb = ttk.Combobox(search_frame, textvariable=self.category_var,
                                   values=list(BiliMarketAPI.CATEGORY_MAP.keys()))
        category_cb.grid(row=0, column=1, padx=5, sticky="ew")
        category_cb.current(0)

        ttk.Label(search_frame, text="关键词:").grid(row=1, column=0, padx=5, sticky="w")
        self.keyword1 = ttk.Entry(search_frame)
        self.keyword1.grid(row=1, column=1, padx=5, sticky="ew")
        self.keyword2 = ttk.Entry(search_frame)
        self.keyword2.grid(row=1, column=2, padx=5, sticky="ew")

        ttk.Label(search_frame, text="价格区间:").grid(row=2, column=0, padx=5, sticky="w")
        self.price_range_var = tk.StringVar()
        price_range_cb = ttk.Combobox(search_frame, textvariable=self.price_range_var,
                                      values=list(BiliMarketAPI.PRICE_RANGES.keys()))
        price_range_cb.grid(row=2, column=1, padx=5, sticky="ew")
        price_range_cb.current(0)

        ttk.Label(search_frame, text="折扣范围:").grid(row=3, column=0, padx=5, sticky="w")
        self.discount_var = tk.StringVar()
        discount_cb = ttk.Combobox(search_frame, textvariable=self.discount_var,
                                   values=["默认全选", "3折以下", "3-5折", "5-7折", "7折以上"])
        discount_cb.grid(row=3, column=1, padx=5, sticky="ew")
        discount_cb.current(0)

        ttk.Label(search_frame, text="排序方式:").grid(row=4, column=0, padx=5, sticky="w")
        self.sort_var = tk.StringVar(value="默认排序")
        sort_cb = ttk.Combobox(search_frame, textvariable=self.sort_var,
                               values=list(BiliMarketAPI.SORT_MAP.keys()))
        sort_cb.grid(row=4, column=1, padx=5, sticky="ew")

        ttk.Label(search_frame, text="搜索间隔（秒）:").grid(row=5, column=0, padx=5, sticky="w")
        self.interval_entry = ttk.Entry(search_frame, width=10)
        self.interval_entry.grid(row=5, column=1, padx=5, sticky="w")
        self.interval_entry.insert(0, "1.6")

        ttk.Label(search_frame, text="最大搜索数:").grid(row=6, column=0, padx=5, sticky="w")
        self.max_results_entry = ttk.Entry(search_frame, width=10)
        self.max_results_entry.grid(row=6, column=1, padx=5, sticky="w")
        self.max_results_entry.insert(0, "500")

        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=5)
        ttk.Button(control_frame, text="开始搜索", command=self.start_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="停止搜索", command=self.stop_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="选择路径", command=self.set_save_path).pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar()
        ttk.Label(control_frame, textvariable=self.status_var).pack(side=tk.RIGHT, padx=5)

        log_frame = ttk.LabelFrame(main_frame, text="实时日志")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

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
        try:
            interval = float(self.interval_entry.get())
            if interval < 0:
                raise ValueError("搜索间隔不能为负数")

            max_results = int(self.max_results_entry.get())
            if max_results <= 0:
                raise ValueError("最大搜索数必须是正整数")

            return {
                "category": BiliMarketAPI.CATEGORY_MAP[self.category_var.get()],
                "price_range": BiliMarketAPI.PRICE_RANGES[self.price_range_var.get()],
                "keywords": [self.keyword1.get(), self.keyword2.get()],
                "sort_type": BiliMarketAPI.SORT_MAP[self.sort_var.get()],
                "discount": self._get_discount(),
                "cookie": self.cookie_text.get("1.0", tk.END).strip(),
                "interval": interval,
                "max_results": max_results
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
        if not self.cookie_text.get("1.0", tk.END).strip():
            messagebox.showwarning("警告", "必须输入有效Cookie！")
            return False

        if not self.export_path:
            messagebox.showwarning("警告", "请先选择保存路径！")
            return False

        return True

    def run_search(self, params):
        self.spider.retry_count = 0
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
            if self.spider.results:
                self._save_results(self.spider.results)
                self._log(f"已保存当前 {len(self.spider.results)} 条结果")
            else:
                self._log("当前无结果可保存")

    def _log(self, message, retry=False):
        self.log_area.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        if retry:
            self.log_area.tag_add("retry", f"{self.log_area.index(tk.END)} linestart", f"{self.log_area.index(tk.END)} lineend")
            self.log_area.tag_config("retry", foreground="orange")
        self.log_area.see(tk.END)
        self.window.update()

    def _save_results(self, results):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"bili_results_{timestamp}"

        csv_path = f"{self.export_path}/{base_name}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["name", "price", "link"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        txt_path = f"{self.export_path}/{base_name}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            for item in results:
                f.write(f"名称：{item['name']}\n价格：{item['price']}元\n链接：{item['link']}\n\n")

        self._log(f"结果已保存至：\n{csv_path}\n{txt_path}")


if __name__ == "__main__":
    app = SpiderGUI()
    app.window.mainloop()