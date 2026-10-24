"""Freshness allowance for CVM IPE's officially weekly bulk archive.

The bulletin is fetched daily, but the underlying archive is not republished
daily. Seven calendar days plus three days of delivery tolerance avoids false
production failures while still detecting genuinely stale archives.
"""
CVM_IPE_MAX_AGE_DAYS = 10
