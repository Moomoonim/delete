import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PW  = os.environ["GMAIL_APP_PW"]
TO_EMAILS     = os.environ["TO_EMAILS"].split(",")

WATCHLIST = {
    "005930.KS": "삼성전자",
    "COHR":  "코히런트",
    "RKLB":  "로켓랩",
    "NVDA":  "엔비디아",
    "TSLA":  "테슬라",
    "MSTR":  "스트래티지",
    "ARKG":  "ARKG ETF",
    "INOD":  "이노데이터",
}

def send_email(subject, body):
    try:
        pw = GMAIL_APP_PW.replace(" ", "")
        smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp.login(GMAIL_ADDRESS, pw)
        for to in TO_EMAILS:
            to = to.strip()
            msg = MIMEMultipart()
            msg["From"]    = GMAIL_ADDRESS
            msg["To"]      = to
            msg["Subject"] = subject
            msg.attach(MIMEText(str(body), "plain", "utf-8"))
            smtp.sendmail(GMAIL_ADDRESS, to, msg.as_string())
            print("전송 완료 -> " + to)
        smtp.quit()
        return True
    except Exception as e:
        print("전송 실패: " + str(e))
        return False

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100 / (1 + g / (l + 1e-10))

def macd(s, f=12, sw=26, sg=9):
    m = s.ewm(span=f, adjust=False).mean() - s.ewm(span=sw, adjust=False).mean()
    return m, m.ewm(span=sg, adjust=False).mean()

def get_df(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple)
                      else c.lower() for c in df.columns]
        return df.dropna()
    except:
        return None

def judge(df):
    if df is None or len(df) < 60:
        return None

    cl = df["close"].squeeze()
    op = df["open"].squeeze()
    hi = df["high"].squeeze()
    vo = df["volume"].squeeze()

    R    = rsi(cl)
    M, S = macd(cl)

    ma5   = cl.rolling(5).mean()
    ma20  = cl.rolling(20).mean()
    ma60  = cl.rolling(60).mean()
    ma120 = cl.rolling(120).mean()
    vavg  = vo.rolling(20).mean()

    def f(x):  return float(x.iloc[-1])
    def f2(x): return float(x.iloc[-2])

    c0 = f(cl);  o0 = f(op)
    v0 = f(vo);  va = max(f(vavg), 1)
    r0 = f(R)
    m0 = f(M);   s0 = f(S)
    m1 = f2(M);  s1 = f2(S)

    ma5_0   = f(ma5);   ma5_1  = f2(ma5)
    ma20_0  = f(ma20);  ma20_1 = f2(ma20)
    ma60_0  = f(ma60);  ma60_1 = f2(ma60)
    ma120_0 = f(ma120)

    score   = 0
    reasons = []

    # 1. 이동평균선 정배열/역배열
    if ma5_0 > ma20_0 > ma60_0 > ma120_0:
        score += 3
        reasons.append("[+3] 완전 정배열 (세력 이탈 없음)")
    elif ma5_0 > ma20_0 > ma60_0:
        score += 2
        reasons.append("[+2] 정배열 유지 중")
    elif ma5_0 < ma20_0 < ma60_0 < ma120_0:
        score -= 3
        reasons.append("[-3] 완전 역배열 (추세 하락)")
    elif ma5_0 < ma20_0 < ma60_0:
        score -= 2
        reasons.append("[-2] 역배열 진행 중")

    # 2. 5일선
    above_ma5 = c0 > ma5_0
    near_ma5  = abs(c0 - ma5_0) / (ma5_0 + 1e-10) < 0.03
    below_ma5 = c0 < ma5_0 * 0.97

    if above_ma5:
        score += 1
        reasons.append("[+1] 5일선 위에서 유지")
    elif near_ma5 and c0 < o0:
        score += 1
        reasons.append("[+1] 5일선 눌림목 (구라 음봉 가능성)")
    elif below_ma5:
        score -= 2
        reasons.append("[-2] 5일선 이탈 (손절 기준 접근)")

    # 3. MACD
    if m1 < s1 and m0 > s0:
        score += 2
        reasons.append("[+2] MACD 골든크로스")
    elif m0 > s0 and m0 > 0:
        score += 1
        reasons.append("[+1] MACD 양수 유지")
    elif m1 > s1 and m0 < s0:
        score -= 2
        reasons.append("[-2] MACD 데드크로스")
    elif m0 < s0 and m0 < 0:
        score -= 1
        reasons.append("[-1] MACD 음수 구간")

    # 4. 거래량
    vol_ratio = v0 / va
    if vol_ratio >= 2.0 and c0 > o0:
        score += 2
        reasons.append("[+2] 거래량 급증 양봉 (" + "{:.1f}".format(vol_ratio) + "x) 세력 매수")
    elif vol_ratio >= 1.5 and c0 > o0:
        score += 1
        reasons.append("[+1] 거래량 증가 양봉 (" + "{:.1f}".format(vol_ratio) + "x)")
    elif vol_ratio < 0.7 and c0 < o0:
        score += 1
        reasons.append("[+1] 거래량 감소 음봉 (" + "{:.1f}".format(vol_ratio) + "x) 눌림목")
    elif vol_ratio >= 2.0 and c0 < o0:
        score -= 2
        reasons.append("[-2] 거래량 급증 음봉 (" + "{:.1f}".format(vol_ratio) + "x) 세력 매도")

    # 5. RSI
    if r0 < 30:
        score += 1
        reasons.append("[+1] RSI 과매도 (" + "{:.1f}".format(r0) + ") 반등 가능")
    elif r0 > 75:
        score -= 1
        reasons.append("[-1] RSI 과매수 (" + "{:.1f}".format(r0) + ") 조정 가능")
    else:
        reasons.append("[ 0] RSI 중립 (" + "{:.1f}".format(r0) + ")")

    # 최종 판정
    if score >= 5:
        verdict = "[강한매수] 적극 진입 검토"
    elif score >= 2:
        verdict = "[매수검토] 분할 진입 검토"
    elif score >= -1:
        verdict = "[홀딩] 관망 유지"
    elif score >= -4:
        verdict = "[매도검토] 부분 청산 검토"
    else:
        verdict = "[강한매도] 즉시 청산 검토"

    return {
        "verdict":   verdict,
        "score":     score,
        "price":     c0,
        "rsi":       r0,
        "vol_ratio": vol_ratio,
        "reasons":   reasons,
    }

def run():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print("체크 시작: " + now_str)

    strong_buy  = []
    buy         = []
    hold        = []
    sell        = []
    strong_sell = []

    for ticker, name in WATCHLIST.items():
        print(name + " (" + ticker + ")...", end=" ")
        df  = get_df(ticker)
        res = judge(df)

        if res is None:
            print("데이터 부족")
            continue

        print("점수 " + str(res["score"]) + " -> " + res["verdict"])

        item = {
            "name":    name,
            "ticker":  ticker,
            "verdict": res["verdict"],
            "score":   res["score"],
            "price":   res["price"],
            "rsi":     res["rsi"],
            "vol_ratio": res["vol_ratio"],
            "reasons": res["reasons"],
        }

        if   res["score"] >= 5:  strong_buy.append(item)
        elif res["score"] >= 2:  buy.append(item)
        elif res["score"] >= -1: hold.append(item)
        elif res["score"] >= -4: sell.append(item)
        else:                    strong_sell.append(item)

    lines = []
    lines.append("[트레이딩 종합 판정 요약]")
    lines.append("분석 시각: " + now_str)
    lines.append("종목 수: " + str(len(WATCHLIST)) + "개")
    lines.append("=" * 35)

    def add_section(title, items):
        if not items:
            return
        lines.append("")
        lines.append(title + " (" + str(len(items)) + "종목)")
        lines.append("-" * 35)
        for it in sorted(items, key=lambda x: -abs(x["score"])):
            lines.append("- " + it["name"] + " (" + it["ticker"] + ")")
            lines.append("  현재가: " + "{:,.2f}".format(it["price"]) +
                         "  |  점수: " + str(it["score"]))
            lines.append("  RSI: " + "{:.1f}".format(it["rsi"]) +
                         "  |  거래량: " + "{:.1f}".format(it["vol_ratio"]) + "x")
            lines.append("  => " + it["verdict"])
            for r in it["reasons"]:
                lines.append("     " + r)

    add_section("[강한매도] 즉시 청산 검토", strong_sell)
    add_section("[매도검토] 부분 청산",      sell)
    add_section("[홀딩] 관망 유지",          hold)
    add_section("[매수검토] 분할 진입",       buy)
    add_section("[강한매수] 적극 진입",       strong_buy)

    lines.append("")
    lines.append("=" * 35)
    lines.append("판정기준: 이동평균선 + 5일선 + MACD + 거래량 + RSI")

    body = "\n".join(lines)

    if strong_sell:
        subject = "[즉시청산] " + str(len(strong_sell)) + "종목 | " + now_str
    elif strong_buy:
        subject = "[강한매수] " + str(len(strong_buy)) + "종목 | " + now_str
    elif sell or buy:
        subject = "[신호발생] " + str(len(sell) + len(buy)) + "종목 | " + now_str
    else:
        subject = "[전종목홀딩] " + now_str

    send_email(subject, body)
    print("완료")

if __name__ == "__main__":
    run()
