# Name Reports

## Purpose

Dibs answers one question for a list of candidate names: can I call dibs on this name? It checks each candidate against Companies House, domains and UK trademarks, tries common company-name variants when the base name is taken, and gives each name a clear verdict with the evidence behind it, so the author can shortlist names in minutes instead of running every check by hand.

## Requirements

### Requirement: Candidates are checked in a batch

The system SHALL accept a list of one or more candidate names and SHALL return one report per candidate, in the order given, each covering the Companies House, domain and trademark checks.

#### Scenario: Three candidates
- GIVEN the candidates "Messier", "Onoma" and "Dibs"
- WHEN they are checked
- THEN three reports are returned, in that order
- AND each report contains a Companies House result, domain results and a trademark result

### Requirement: Every name gets a verdict

Each report SHALL carry exactly one verdict: "conflict" when any check found a conflict, otherwise "check manually" when any check could not be completed automatically or found a possible conflict, otherwise "clear".

#### Scenario: One conflict wins
- GIVEN a candidate whose domains are available and trademark check is clear
- AND an active company with the same name exists
- WHEN it is checked
- THEN its verdict is "conflict"

#### Scenario: Manual check needed
- GIVEN a candidate with no conflicts
- AND a trademark check that could not be completed automatically
- WHEN it is checked
- THEN its verdict is "check manually"

#### Scenario: All clear
- GIVEN a candidate with no conflicts, no possible conflicts and every check completed
- WHEN it is checked
- THEN its verdict is "clear"

### Requirement: Verdicts show their evidence

Every conflict, possible conflict and manual check in a report SHALL include what was found and a link where the author can see it for themselves.

#### Scenario: Company conflict evidence
- GIVEN a candidate that conflicts with an existing company
- WHEN the report is returned
- THEN it names the existing company, its company number and a link to its Companies House page

### Requirement: Taken names suggest variants

When a candidate conflicts at Companies House, the system SHALL also check the candidate with each configured suffix added (by default "Labs" and "Studio") and SHALL report each variant with its own verdict alongside the base name.

#### Scenario: Base name taken
- GIVEN the candidate "Interstellar AI" conflicts with an existing company
- WHEN it is checked
- THEN the report also contains verdicts for "Interstellar AI Labs" and "Interstellar AI Studio"

#### Scenario: Base name free
- GIVEN a candidate with no Companies House conflict
- WHEN it is checked
- THEN no variants are reported for it

### Requirement: Dibs never registers anything

The system MUST only read. It SHALL NOT register companies, buy domains, file trademarks or reserve names anywhere.

#### Scenario: Clear name
- GIVEN a candidate whose verdict is "clear"
- WHEN the check completes
- THEN nothing has been registered, bought or reserved
