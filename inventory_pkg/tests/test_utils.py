"""
Tests for inventory_pkg — covers SKU validation, brand detection,
channel detection, file pattern matching, and config loading.

Run with:
    python -m pytest inventory_pkg/tests/ -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from inventory_pkg.utils import (
    is_valid_sku,
    brand_group,
    detect_brand_from_name,
    detect_brand_from_filename,
    detect_channel_from_filename,
    safe_filename,
    to_num,
    fmt_number,
    merge_row,
)
from inventory_pkg.constants import BRAND_KEYWORD_MAP, ALL_BRANDS
from inventory_pkg.config import BRAND_GROUPS, BRAND_ALIASES, FILE_PATTERNS


# =============================================================================
# SKU VALIDATION
# =============================================================================

class TestIsValidSku:

    def test_valid_10_digit_sku(self):
        assert is_valid_sku("1000048706") is True

    def test_valid_13_digit_sku(self):
        assert is_valid_sku("2000047394003") is True

    def test_valid_starts_with_2(self):
        assert is_valid_sku("2000048706") is True

    def test_invalid_too_short(self):
        assert is_valid_sku("99999") is False

    def test_invalid_too_long(self):
        assert is_valid_sku("10000487060001") is False

    def test_invalid_letters(self):
        assert is_valid_sku("ABC1234567") is False

    def test_invalid_starts_with_3(self):
        assert is_valid_sku("3000048706") is False

    def test_invalid_starts_with_0(self):
        assert is_valid_sku("0000048706") is False

    def test_invalid_empty(self):
        assert is_valid_sku("") is False

    def test_strips_whitespace(self):
        assert is_valid_sku("  1000048706  ") is True

    def test_integer_input(self):
        assert is_valid_sku(1000048706) is True


# =============================================================================
# BRAND GROUP
# =============================================================================

class TestBrandGroup:

    def test_ssiebg_brand(self):
        assert brand_group("Lacoste") == "SSIEBG"

    def test_ssiebg_calvin_klein(self):
        assert brand_group("Calvin Klein") == "SSIEBG"

    def test_payless_brand(self):
        assert brand_group("Payless") == "PAYLESS"

    def test_slci_brand(self):
        assert brand_group("Old Navy") == "SLCI"

    def test_slci_gap(self):
        assert brand_group("Gap") == "SLCI"

    def test_unknown_brand(self):
        assert brand_group("Unknown Brand XYZ") == "UNKNOWN"

    def test_empty_brand(self):
        assert brand_group("") == "UNKNOWN"

    def test_none_brand(self):
        assert brand_group(None) == "UNKNOWN"


# =============================================================================
# BRAND DETECTION FROM NAME
# =============================================================================

class TestDetectBrandFromName:

    def test_detects_lacoste(self):
        assert detect_brand_from_name("Lacoste Polo Shirt White") == "Lacoste"

    def test_detects_calvin_klein(self):
        assert detect_brand_from_name("Calvin Klein Jeans Slim Fit") == "Calvin Klein"

    def test_detects_tommy_hilfiger(self):
        assert detect_brand_from_name("Tommy Hilfiger Classic Tee") == "Tommy Hilfiger"

    def test_detects_tommy_alias(self):
        assert detect_brand_from_name("Tommy Classic Polo") == "Tommy Hilfiger"

    def test_detects_payless(self):
        assert detect_brand_from_name("Payless Women Sandals") == "Payless"

    def test_detects_old_navy(self):
        assert detect_brand_from_name("Old Navy Kids Jeans") == "Old Navy"

    def test_returns_none_for_unknown(self):
        assert detect_brand_from_name("Generic Product Name") is None

    def test_case_insensitive(self):
        assert detect_brand_from_name("LACOSTE POLO") == "Lacoste"


# =============================================================================
# BRAND DETECTION FROM FILENAME
# =============================================================================

class TestDetectBrandFromFilename:

    def test_zalora_template_lacoste(self):
        assert detect_brand_from_filename(
            "Lacoste_SellerStockTemplate_2026-05-07.xlsx"
        ) == "Lacoste"

    def test_zalora_template_calvin_klein(self):
        assert detect_brand_from_filename(
            "CalvinKlein_SellerStockTemplate_2026-05-07.xlsx"
        ) == "Calvin Klein"

    def test_zalora_template_dash_separator(self):
        assert detect_brand_from_filename(
            "Lacoste-SellerStockTemplate_2026-05-07.xlsx"
        ) == "Lacoste"

    def test_lazada_price_file(self):
        result = detect_brand_from_filename("price_Lacoste_2026.xlsx")
        assert result == "Lacoste"

    def test_returns_none_for_no_brand(self):
        result = detect_brand_from_filename("random_file_no_brand.xlsx")
        assert result is None


# =============================================================================
# CHANNEL DETECTION FROM FILENAME
# =============================================================================

class TestDetectChannelFromFilename:

    def test_mass_file_is_shopee(self):
        assert detect_channel_from_filename("MASS_Lacoste_2026.zip") == "Channel_Shopee"

    def test_shopee_in_name(self):
        assert detect_channel_from_filename("shopee_stock.xlsx") == "Channel_Shopee"

    def test_price_file_is_lazada(self):
        assert detect_channel_from_filename("price_Lacoste_2026.xlsx") == "Channel_Lazada"

    def test_lazada_in_name(self):
        assert detect_channel_from_filename("lazada_stock.xlsx") == "Channel_Lazada"

    def test_zalora_in_name(self):
        assert detect_channel_from_filename("zalora_stock.xlsx") == "Channel_Zalora"

    def test_seller_stock_template_is_zalora(self):
        assert detect_channel_from_filename(
            "Lacoste_SellerStockTemplate_2026.xlsx"
        ) == "Channel_Zalora"

    def test_unknown_file_returns_none(self):
        assert detect_channel_from_filename("random_file.xlsx") is None


# =============================================================================
# FILE PATTERN CONFIG
# =============================================================================

class TestFilePatterns:

    def test_shopee_prefixes_exist(self):
        assert "mass" in FILE_PATTERNS["shopee_prefixes"]

    def test_lazada_prefixes_exist(self):
        assert "price" in FILE_PATTERNS["lazada_prefixes"]

    def test_zalora_keywords_exist(self):
        assert "sellerstocktemplate" in FILE_PATTERNS["zalora_keywords"]

    def test_ordazzle_prefixes_exist(self):
        assert "exl" in FILE_PATTERNS["ordazzle_prefixes"]
        assert "exp" in FILE_PATTERNS["ordazzle_prefixes"]

    def test_sap_prefixes_exist(self):
        assert "article" in FILE_PATTERNS["sap_prefixes"]

    def test_modify_prefixes_exist(self):
        assert "modify" in FILE_PATTERNS["modify_prefixes"]


# =============================================================================
# CONFIG LOADING
# =============================================================================

class TestConfig:

    def test_brand_groups_not_empty(self):
        assert len(BRAND_GROUPS) > 0

    def test_ssiebg_group_exists(self):
        groups = [g["group"] for g in BRAND_GROUPS]
        assert "SSIEBG" in groups

    def test_payless_group_exists(self):
        groups = [g["group"] for g in BRAND_GROUPS]
        assert "PAYLESS" in groups

    def test_slci_group_exists(self):
        groups = [g["group"] for g in BRAND_GROUPS]
        assert "SLCI" in groups

    def test_each_group_has_required_keys(self):
        required = {"group", "brands", "warehouse", "sap_site", "storage_loc"}
        for g in BRAND_GROUPS:
            assert required.issubset(g.keys()), f"Group {g.get('group')} missing keys"

    def test_each_group_has_brands(self):
        for g in BRAND_GROUPS:
            assert len(g["brands"]) > 0, f"Group {g['group']} has no brands"

    def test_brand_aliases_not_empty(self):
        assert len(BRAND_ALIASES) > 0

    def test_all_brands_in_keyword_map(self):
        for brand in ALL_BRANDS:
            assert brand.lower() in BRAND_KEYWORD_MAP, f"{brand} missing from BRAND_KEYWORD_MAP"


# =============================================================================
# HELPERS
# =============================================================================

class TestHelpers:

    def test_safe_filename_spaces(self):
        assert " " not in safe_filename("Calvin Klein")

    def test_safe_filename_apostrophe(self):
        assert "'" not in safe_filename("women'secret")

    def test_safe_filename_ampersand(self):
        assert safe_filename("MakeRoom & More") == "MakeRoomAndMore"

    def test_to_num_integer(self):
        assert to_num("42") == 42.0

    def test_to_num_float(self):
        assert to_num("3.14") == 3.14

    def test_to_num_invalid(self):
        assert to_num("abc") == 0.0

    def test_to_num_none(self):
        assert to_num(None) == 0.0

    def test_fmt_number_whole(self):
        assert fmt_number(3.0) == 3

    def test_fmt_number_fractional(self):
        assert fmt_number(3.5) == 3.5

    def test_fmt_number_string(self):
        assert fmt_number("hello") == "hello"

    def test_fmt_number_none(self):
        assert fmt_number(None) == ""

    def test_merge_row_sums_numbers(self):
        target = {"qty": 10}
        merge_row(target, {"qty": 5})
        assert target["qty"] == 15.0

    def test_merge_row_adds_missing_keys(self):
        target = {"qty": 10}
        merge_row(target, {"stock": 20})
        assert target["stock"] == 20

    def test_merge_row_keeps_non_numeric(self):
        target = {"sku": "ABC"}
        merge_row(target, {"sku": "XYZ"})
        assert target["sku"] == "ABC"
