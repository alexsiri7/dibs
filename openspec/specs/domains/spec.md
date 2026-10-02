# Domains

## Purpose

A brand needs a web address. This capability reports whether the candidate's domain is free under each ending the author cares about.

## Requirements

### Requirement: Configured endings are checked

The system SHALL check the candidate, lowercased with spaces and punctuation removed, under each configured domain ending. The default endings SHALL be .com, .co.uk, .ai and .io.

#### Scenario: Default endings
- GIVEN no endings are configured
- WHEN the candidate "Dibs" is checked
- THEN results are reported for dibs.com, dibs.co.uk, dibs.ai and dibs.io

#### Scenario: Custom endings
- GIVEN the configured endings are .com and .dev
- WHEN the candidate "Dibs" is checked
- THEN results are reported for dibs.com and dibs.dev only

### Requirement: Each domain is available, taken or unknown

For each domain the system SHALL report "available" when no registration exists, "taken" when one exists, and "check manually" when the lookup fails or the ending cannot be looked up. A taken domain SHALL NOT make the candidate's verdict a conflict on its own.

#### Scenario: Registered domain
- GIVEN dibs.com is registered
- WHEN "Dibs" is checked
- THEN dibs.com is reported as taken
- AND this alone does not make the verdict "conflict"

#### Scenario: Lookup fails
- GIVEN the lookup for dibs.ai fails
- WHEN "Dibs" is checked
- THEN dibs.ai is reported as "check manually"
