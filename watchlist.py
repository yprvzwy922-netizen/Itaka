"""
Default watchlist (ticker, company, sector, bucket, conviction, delta band).
Plain data — no Streamlit — so the app (via shared.py) and the GitHub scripts
share one copy. The live list in Supabase overrides these per ticker.
"""
# ── Default watchlist ─────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    {"ticker": "IREN",  "company": "IREN Ltd",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "CIFR",  "company": "Cipher Digital",          "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "NBIS",  "company": "Nebius Group",            "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CRWV",  "company": "CoreWeave",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CEG",   "company": "Constellation Energy",    "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "DGXX",  "company": "Digi Power X",            "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "VRT",   "company": "Vertiv",                  "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "GEV",   "company": "GE Vernova",              "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVDA",  "company": "NVIDIA",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MU",    "company": "Micron",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMD",   "company": "Advanced Micro Devices",  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "GOOG",  "company": "Alphabet",                "sector": "Technology",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "BB",    "company": "BlackBerry",              "sector": "Technology",           "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "UBER",  "company": "Uber Technologies",       "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "LLY",   "company": "Eli Lilly",               "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVO",   "company": "Novo Nordisk",            "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMGN",  "company": "Amgen",                   "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "HIMS",  "company": "Hims & Hers",             "sector": "Healthcare",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "VKTX",  "company": "Viking Therapeutics",     "sector": "Healthcare",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "IBRX",  "company": "ImmunityBio",             "sector": "Healthcare",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # ── Added 2026-06-18 from broker "Cash secured Puts" list ──────────────────
    # AI compute / semis
    {"ticker": "AVGO",  "company": "Broadcom",                "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MRVL",  "company": "Marvell Technology",      "sector": "Semiconductors",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "AXTI",  "company": "AXT Inc",                 "sector": "Semiconductors",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    # Data centers / AI
    {"ticker": "PENG",  "company": "Penguin Solutions",       "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "NUAI",  "company": "New Era Energy & Digital", "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "OSS",   "company": "One Stop Systems",        "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Power / energy
    {"ticker": "VST",   "company": "Vistra",                  "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "UUUU",  "company": "Energy Fuels (uranium)",  "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "FLNC",  "company": "Fluence Energy",          "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "TE",    "company": "T1 Energy (VERIFY)",      "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Big tech / software
    {"ticker": "AAPL",  "company": "Apple",                   "sector": "Technology",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NOW",   "company": "ServiceNow (VERIFY PX)",  "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "RDDT",  "company": "Reddit",                  "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ZETA",  "company": "Zeta Global",             "sector": "Technology",           "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    {"ticker": "ADEA",  "company": "Adeia",                   "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "MGNI",  "company": "Magnite",                 "sector": "Technology",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "OPEN",  "company": "Opendoor Technologies",   "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "ONDS",  "company": "Ondas Holdings",          "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "OUST",  "company": "Ouster (lidar)",          "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "KEEL",  "company": "KEEL (VERIFY)",           "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Quantum (binary, very high IV)
    {"ticker": "QBTS",  "company": "D-Wave Quantum",          "sector": "Quantum",              "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "RGTI",  "company": "Rigetti Computing",       "sector": "Quantum",              "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "QUBT",  "company": "Quantum Computing Inc",   "sector": "Quantum",              "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Space & defense
    {"ticker": "KTOS",  "company": "Kratos Defense",          "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "RKLB",  "company": "Rocket Lab",              "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ASTS",  "company": "AST SpaceMobile",         "sector": "Space & Defense",      "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "SPCX",  "company": "SpaceX",                  "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    # Financials
    {"ticker": "ICE",   "company": "Intercontinental Exch.",  "sector": "Financials",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "PLMR",  "company": "Palomar Holdings",        "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "INTR",  "company": "Inter & Co",              "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "PGY",   "company": "Pagaya Technologies",     "sector": "Financials",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "QXO",   "company": "QXO Inc",                 "sector": "Industrials",          "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    # Healthcare
    {"ticker": "HALO",  "company": "Halozyme Therapeutics",   "sector": "Healthcare",           "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "OSCR",  "company": "Oscar Health",            "sector": "Healthcare",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ARDX",  "company": "Ardelyx",                 "sector": "Healthcare",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Crypto & digital assets (ETFs/proxies — selling puts = bullish crypto)
    {"ticker": "IBIT",  "company": "iShares Bitcoin Trust",   "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "ETHA",  "company": "iShares Ethereum Trust",  "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "GLXY",  "company": "Galaxy Digital",          "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    # ── Added 2026-06-25: CORE anchors to broaden tradable setups (on-theme,
    #    mega-cap, deep options) — addresses being under the Core target ──────────
    {"ticker": "MSFT",  "company": "Microsoft",               "sector": "Technology",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "META",  "company": "Meta Platforms",          "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "AMZN",  "company": "Amazon",                  "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "TSM",   "company": "Taiwan Semiconductor",    "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "ANET",  "company": "Arista Networks",         "sector": "Data Centers & AI",    "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ORCL",  "company": "Oracle",                  "sector": "Data Centers & AI",    "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ETN",   "company": "Eaton",                   "sector": "Energy & Power",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ABBV",  "company": "AbbVie",                  "sector": "Healthcare",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    # ── Growth complements: liquid, on-theme, frequent setups ──────────────────
    {"ticker": "PLTR",  "company": "Palantir",                "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "DELL",  "company": "Dell Technologies",       "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Wheel"},
    {"ticker": "SMCI",  "company": "Super Micro Computer",    "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    # ── Added 2026-06-25: premium machines + diversifiers (lower AI correlation) ─
    {"ticker": "TSLA",  "company": "Tesla",                   "sector": "Consumer",             "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "CRWD",  "company": "CrowdStrike",             "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "APP",   "company": "AppLovin",                "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "COIN",  "company": "Coinbase",                "sector": "Crypto & Digital",     "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "MA",    "company": "Mastercard",             "sector": "Financials",           "bucket": "Core",        "conviction": 4, "delta_band": "Income"},
    {"ticker": "JPM",   "company": "JPMorgan Chase",          "sector": "Financials",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "CAT",   "company": "Caterpillar",             "sector": "Industrials",          "bucket": "Core",        "conviction": 3, "delta_band": "Wheel"},
    {"ticker": "UNH",   "company": "UnitedHealth",            "sector": "Healthcare",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "HOOD",  "company": "Robinhood",               "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "SOFI",  "company": "SoFi Technologies",       "sector": "Financials",           "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    {"ticker": "XOM",   "company": "ExxonMobil",              "sector": "Energy & Power",       "bucket": "Core",        "conviction": 4, "delta_band": "Income"},
    # ── Diversifiers: high quality, low beta / low correlation to the AI trade (added 2026-10) ──
    {"ticker": "CB",    "company": "Chubb",                  "sector": "Financials",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "PGR",   "company": "Progressive",            "sector": "Financials",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "V",     "company": "Visa",                   "sector": "Financials",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "CME",   "company": "CME Group",              "sector": "Financials",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "RSG",   "company": "Republic Services",      "sector": "Industrials",          "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "WM",    "company": "Waste Management",       "sector": "Industrials",          "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "JNJ",   "company": "Johnson & Johnson",      "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "ABT",   "company": "Abbott Laboratories",    "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "SYK",   "company": "Stryker",                "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "KO",    "company": "Coca-Cola",              "sector": "Consumer",             "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "PG",    "company": "Procter & Gamble",       "sector": "Consumer",             "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "PEP",   "company": "PepsiCo",                "sector": "Consumer",             "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "ED",    "company": "Consolidated Edison",    "sector": "Utilities",            "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "DUK",   "company": "Duke Energy",            "sector": "Utilities",            "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "VZ",    "company": "Verizon",                "sector": "Communication",        "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
]

SECTORS = sorted(set(w["sector"] for w in DEFAULT_WATCHLIST))
