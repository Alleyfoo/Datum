"""Checks on what an answer says: only what the facts say, and only to the customer it is for."""

from .answers import Check, check_answer, customer_part, dates_in, describe, numbers_in

__all__ = ["Check", "check_answer", "customer_part", "dates_in", "describe", "numbers_in"]
