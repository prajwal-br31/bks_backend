"""Tests for Bank Feed functionality."""

import pytest
from datetime import datetime
from app.services.bank_feed.csv_parser import (
    ChaseCsvParser,
    GenericCsvParser,
    get_parser_for_content,
    ParsedTransaction,
)


class TestChaseCsvParser:
    """Tests for Chase CSV parser."""

    def test_detect_chase_format(self):
        """Test detection of Chase CSV format."""
        parser = ChaseCsvParser()
        
        # Chase format with standard headers
        chase_csv = b"Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
        assert parser.detect(chase_csv) is True
        
        # Non-Chase format
        generic_csv = b"Date,Description,Amount\n"
        assert parser.detect(generic_csv) is False

    def test_parse_chase_transactions(self):
        """Test parsing Chase transactions."""
        parser = ChaseCsvParser()
        
        csv_content = b"""Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,01/15/2025,AMAZON PURCHASE,-45.99,DEBIT,1234.56,
CREDIT,01/14/2025,PAYROLL DEPOSIT,2500.00,CREDIT,1280.55,
DEBIT,01/13/2025,CHECK PAYMENT,-100.00,DEBIT,-1219.45,1234
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 3
        assert result.skipped_rows == 0
        assert result.bank_name == "Chase"
        assert len(result.transactions) == 3
        
        # Check first transaction
        txn = result.transactions[0]
        assert txn.description == "AMAZON PURCHASE"
        assert txn.amount == 45.99
        assert txn.type == "debit"
        assert txn.balance == 1234.56

    def test_parse_dates(self):
        """Test various date formats."""
        parser = ChaseCsvParser()
        
        csv_content = b"""Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,01/15/2025,Test,-10.00,DEBIT,100.00,
DEBIT,12/31/24,Test2,-20.00,DEBIT,80.00,
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 2
        assert result.transactions[0].date.month == 1
        assert result.transactions[0].date.day == 15

    def test_handle_empty_rows(self):
        """Test handling of empty/invalid rows."""
        parser = ChaseCsvParser()
        
        csv_content = b"""Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,01/15/2025,Valid,-10.00,DEBIT,100.00,
,,,,,,
DEBIT,invalid_date,Invalid,-20.00,DEBIT,80.00,
DEBIT,01/16/2025,Also Valid,-30.00,DEBIT,50.00,
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 2
        assert result.skipped_rows == 2


class TestGenericCsvParser:
    """Tests for generic CSV parser."""

    def test_auto_detect_columns(self):
        """Test automatic column detection."""
        parser = GenericCsvParser()
        
        csv_content = b"""Transaction Date,Description,Withdrawal,Deposit,Balance
01/15/2025,Coffee Shop,5.50,,100.00
01/14/2025,Salary,,2500.00,2605.50
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 2
        assert result.transactions[0].description == "Coffee Shop"
        assert result.transactions[0].type == "debit"
        assert result.transactions[1].type == "credit"

    def test_single_amount_column(self):
        """Test parsing with single amount column (positive/negative)."""
        parser = GenericCsvParser()
        
        csv_content = b"""Date,Description,Amount
01/15/2025,Expense,-100.00
01/14/2025,Income,500.00
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 2
        assert result.transactions[0].type == "debit"
        assert result.transactions[0].amount == 100.00
        assert result.transactions[1].type == "credit"
        assert result.transactions[1].amount == 500.00

    def test_various_date_formats(self):
        """Test handling of various date formats."""
        parser = GenericCsvParser()
        
        csv_content = b"""Date,Description,Amount
2025-01-15,ISO Format,100.00
01/15/2025,US Format,100.00
15/01/2025,EU Format,100.00
"""
        
        result = parser.parse(csv_content)
        
        # At least the first two should parse
        assert result.parsed_rows >= 2


class TestParserSelection:
    """Tests for parser selection."""

    def test_select_chase_parser(self):
        """Test that Chase format selects Chase parser."""
        chase_csv = b"Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
        parser = get_parser_for_content(chase_csv)
        
        assert isinstance(parser, ChaseCsvParser)

    def test_fallback_to_generic(self):
        """Test fallback to generic parser."""
        generic_csv = b"Date,Description,Amount\n01/15/2025,Test,100.00\n"
        parser = get_parser_for_content(generic_csv)
        
        assert isinstance(parser, GenericCsvParser)


class TestParsedTransaction:
    """Tests for ParsedTransaction dataclass."""

    def test_transaction_creation(self):
        """Test creating a parsed transaction."""
        txn = ParsedTransaction(
            date=datetime(2025, 1, 15),
            description="Test Transaction",
            amount=100.50,
            type="debit",
            balance=500.00,
            row_number=1,
        )
        
        assert txn.date.day == 15
        assert txn.amount == 100.50
        assert txn.type == "debit"

    def test_optional_fields(self):
        """Test optional fields default to None."""
        txn = ParsedTransaction(
            date=datetime(2025, 1, 15),
            description="Test",
            amount=100.0,
            type="credit",
        )
        
        assert txn.balance is None
        assert txn.category is None
        assert txn.check_number is None
        assert txn.external_id is None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self):
        """Test handling of empty file."""
        parser = GenericCsvParser()
        result = parser.parse(b"")
        
        assert result.parsed_rows == 0
        assert len(result.errors) > 0 or len(result.warnings) > 0

    def test_malformed_csv(self):
        """Test handling of malformed CSV."""
        parser = GenericCsvParser()
        result = parser.parse(b"not,a,valid,csv\nwith,wrong,column,count,extra\n")
        
        # Should not crash
        assert result is not None

    def test_unicode_content(self):
        """Test handling of unicode characters."""
        parser = GenericCsvParser()
        
        csv_content = "Date,Description,Amount\n01/15/2025,Café Latté,15.00\n".encode("utf-8")
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 1
        assert "Café" in result.transactions[0].description

    def test_amount_with_currency_symbols(self):
        """Test parsing amounts with currency symbols."""
        parser = GenericCsvParser()
        
        csv_content = b"""Date,Description,Amount
01/15/2025,Purchase,$100.00
01/14/2025,Refund,($50.00)
01/13/2025,Transfer,USD 25.00
"""
        
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 3
        assert result.transactions[0].amount == 100.00
        assert result.transactions[1].amount == 50.00
        assert result.transactions[2].amount == 25.00

    def test_large_file(self):
        """Test handling of larger files."""
        parser = GenericCsvParser()
        
        # Generate 1000 rows
        rows = ["Date,Description,Amount"]
        for i in range(1000):
            rows.append(f"01/{(i % 28) + 1:02d}/2025,Transaction {i},{i * 10}.00")
        
        csv_content = "\n".join(rows).encode("utf-8")
        result = parser.parse(csv_content)
        
        assert result.parsed_rows == 1000
        assert len(result.transactions) == 1000
