# Companies House

## Purpose

A UK company cannot be registered with a name that Companies House treats as the same as an existing company's, and a name that is merely too like one can be challenged later. This capability checks candidates against the live register the way Companies House compares names, so a name that looks different but is legally the same is caught.

## Requirements

### Requirement: Names are compared the way Companies House compares them

The system SHALL treat a candidate as the same as an existing name when they match after ignoring case, spaces, punctuation, the company-type endings "Limited" and "Ltd", and web endings such as ".com", ".co.uk", ".net" and ".org".

#### Scenario: Web ending ignored
- GIVEN an active company named "Interstellar AI Ltd"
- WHEN the candidate "interstellarai.net" is checked
- THEN the Companies House result is a conflict with that company

#### Scenario: Case and spacing ignored
- GIVEN an active company named "Blue Fern Limited"
- WHEN the candidate "BLUEFERN" is checked
- THEN the Companies House result is a conflict with that company

### Requirement: Only live companies conflict

The system SHALL report a conflict only against companies on the register that are not dissolved. Dissolved companies SHALL NOT make a candidate conflict.

#### Scenario: Dissolved company
- GIVEN the only company matching a candidate is dissolved
- WHEN the candidate is checked
- THEN the Companies House result is not a conflict

### Requirement: Near matches are flagged

When no company is the same as the candidate but a live company's name contains the candidate as a whole word, or the candidate contains that company's name as a whole word, the system SHALL report a possible conflict naming that company.

#### Scenario: Name with an extra word
- GIVEN an active company named "Interstellar AI Ltd" and no company the same as "Interstellar AI Labs"
- WHEN the candidate "Interstellar AI Labs" is checked
- THEN the Companies House result is a possible conflict naming "Interstellar AI Ltd"

### Requirement: Unavailable register means manual check

If the register cannot be searched, the system SHALL report the Companies House check as needing a manual check, with a link to search the register for the candidate, rather than reporting it clear.

#### Scenario: Search fails
- GIVEN the Companies House search cannot be reached
- WHEN a candidate is checked
- THEN its Companies House result is "check manually" with a search link
