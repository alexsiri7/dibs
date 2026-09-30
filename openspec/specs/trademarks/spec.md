# Trademarks

## Purpose

A free company name can still infringe a registered trademark. This capability checks the UK trademark register in the classes that matter for software work: class 9 (software) and class 42 (IT services).

## Requirements

### Requirement: UK marks in software classes conflict

The system SHALL report a conflict when a live UK trademark in class 9 or class 42 has the same name as the candidate, compared as in the Companies House capability.

#### Scenario: Live mark in class 42
- GIVEN a live UK trademark "DIBS" registered in class 42
- WHEN the candidate "Dibs" is checked
- THEN the trademark result is a conflict naming that mark

#### Scenario: Mark in an unrelated class
- GIVEN the only UK trademark "DIBS" is in class 30 (food)
- WHEN the candidate "Dibs" is checked
- THEN the trademark result is not a conflict

### Requirement: No guessing when the register cannot be searched

If the trademark register cannot be searched automatically, the system SHALL report the trademark check as "check manually" with a link that opens the UK IPO trademark search for the candidate, and SHALL NOT report it clear.

#### Scenario: Register unavailable
- GIVEN the trademark register cannot be searched automatically
- WHEN a candidate is checked
- THEN its trademark result is "check manually" with a UK IPO search link
