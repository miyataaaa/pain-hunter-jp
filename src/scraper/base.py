"""スクレイパー基底クラス定義モジュール。

ネットワーク設計ノート:
  Yahoo!知恵袋はDNSロードバランシングを使用しており、返ってくるIPが
  アクセス元ネットワーク（WSL2等）からブロックされることがある。
  http.client / requests はDNSで解決したIPを使うため接続タイムアウトが発生する。
  そのため raw socket + ssl で接続し、DNS失敗時はフォールバックIPを試みる。
  証明書検証はSNIで行うため verify_mode は CERT_NONE にしない（check_hostname=True）。
  ただし IP直接接続時はホスト名とIPが一致しないため check_hostname=False + CERT_NONE。
"""

import logging
import socket
import ssl
import time
import urllib.parse
from abc import ABC, abstractmethod

from src.config import config
from src.models import RawQuestion

# DNS解決で取得できるIPがブロックされる場合のフォールバックIP候補
# Yahoo! JAPANのCDNは時間帯・環境によってアクセス可能なセグメントが変わるため複数列挙する
_FALLBACK_IPS: dict[str, list[str]] = {
    "chiebukuro.yahoo.co.jp": ["183.79.48.248", "202.239.2.249", "183.79.49.248"],
    "detail.chiebukuro.yahoo.co.jp": ["183.79.48.248", "202.239.3.249", "183.79.48.249", "183.79.49.249"],
}

# TCP接続テストのタイムアウト（秒）
_TCP_TEST_TIMEOUT = 4

# _get_working_ip のキャッシュ（失敗も含む）。プロセス内で再利用。
# None = 到達不能確認済み、str = 接続可能IP
_ip_cache: dict[str, str | None] = {}


class _SimpleResponse:
    """requests.Responseの互換インターフェース。"""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")


def _tcp_reachable(ip: str, port: int = 443, timeout: float = _TCP_TEST_TIMEOUT) -> bool:
    """TCPレベルで接続可能かテストする。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _resolve_working_ip(host: str) -> str | None:
    """接続可能なIPを返す。DNS優先、失敗時はフォールバックIPを試す。"""
    # DNS解決
    dns_ips: list[str] = []
    try:
        dns_ips = list({addr[4][0] for addr in socket.getaddrinfo(host, 443, socket.AF_INET)})
    except OSError:
        pass

    fallback_ips = _FALLBACK_IPS.get(host, [])
    # DNSのIPを先に試し、次にフォールバック（重複除外）
    candidates = list(dict.fromkeys(dns_ips + fallback_ips))

    for ip in candidates:
        if _tcp_reachable(ip):
            return ip
    return None


class BaseScraper(ABC):
    """すべてのスクレイパーが継承する抽象基底クラス。

    raw socket + ssl を使い、DNS解決IPがブロックされる場合は
    フォールバックIPにフェイルオーバーする。
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def _get_working_ip(self, host: str) -> str | None:
        """ホストへの接続可能IPを返す（プロセス内キャッシュあり）。

        失敗（None）もキャッシュするため、同一プロセス内で到達不能ホストへの
        IP探索を繰り返さない。
        """
        if host not in _ip_cache:
            ip = _resolve_working_ip(host)
            if ip:
                self.logger.info("接続IP確定: %s → %s", host, ip)
            else:
                self.logger.error(
                    "接続可能IPなし: %s (試行IP: %s) — スクレイピングをスキップします",
                    host,
                    _FALLBACK_IPS.get(host, []),
                )
            _ip_cache[host] = ip  # None も記録して再探索を防ぐ
        return _ip_cache[host]

    def _raw_https_get(self, host: str, path: str, ip: str, timeout: int = 15) -> _SimpleResponse:
        """raw socket経由でHTTPS GETリクエストを送信する。"""
        ctx = ssl.create_default_context()
        # IPで接続するためcheck_hostnameを無効化、ただしcertは検証する
        # （Yahoo! JAPANは信頼できるCAで発行された証明書を使用）
        ctx.check_hostname = False

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, 443))
        try:
            tls = ctx.wrap_socket(s, server_hostname=host)
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: {config.USER_AGENT}\r\n"
                f"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\n"
                f"Accept-Language: ja,en;q=0.5\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            tls.sendall(request)
            tls.settimeout(timeout)

            raw = b""
            while True:
                chunk = tls.recv(16384)
                if not chunk:
                    break
                raw += chunk
        finally:
            s.close()

        header_end = raw.find(b"\r\n\r\n")
        if header_end < 0:
            return _SimpleResponse(0, "")

        header_bytes = raw[:header_end]
        body = raw[header_end + 4:].decode("utf-8", errors="replace")

        # ステータスコード取得
        first_line = header_bytes.split(b"\r\n")[0].decode("ascii", errors="replace")
        try:
            status_code = int(first_line.split(" ")[1])
        except (IndexError, ValueError):
            status_code = 0

        return _SimpleResponse(status_code, body)

    def _get(self, url: str, **_kwargs) -> _SimpleResponse | None:
        """GETリクエストを送信する。失敗時はNoneを返す。

        リクエスト後に設定されたインターバル分スリープする。
        """
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.netloc
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query

            ip = self._get_working_ip(host)
            if not ip:
                self.logger.warning("接続IP取得失敗: %s", host)
                return None

            return self._raw_https_get(host, path, ip)

        except Exception as e:
            self.logger.warning("GETエラー url=%s error=%s", url, e)
            return None
        finally:
            time.sleep(config.SCRAPE_INTERVAL_SEC)

    @abstractmethod
    def scrape_category(self, category_major: str, category_minor: str, limit: int) -> list[RawQuestion]:
        """指定カテゴリから質問を取得する。

        Args:
            category_major: 大カテゴリ名
            category_minor: 中カテゴリ名
            limit: 最大取得件数

        Returns:
            RawQuestionのリスト
        """

    @abstractmethod
    def run(
        self,
        date_str: str,
        categories: list[str] | None,
        limit: int,
        dry_run: bool,
    ) -> list[RawQuestion]:
        """スクレイパー全体を実行し、結果をJSONに保存する。

        Args:
            date_str: 実行日付文字列 (YYYY-MM-DD)
            categories: 対象カテゴリ（Noneなら全カテゴリ）
            limit: カテゴリあたりの最大件数
            dry_run: Trueなら実際のHTTP通信をスキップしサンプルデータを返す

        Returns:
            収集したRawQuestionのリスト
        """
