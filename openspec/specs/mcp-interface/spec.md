# MCP Interface

## Purpose

Names get brainstormed in conversation with Claude. Dibs is an MCP server so that Claude can check candidates in the middle of that conversation and bring back the verdicts, without the author leaving the chat.

## Requirements

### Requirement: Names can be checked from an MCP client

The system SHALL expose an MCP tool that takes a list of candidate names and optionally domain endings and variant suffixes, and returns the name reports.

#### Scenario: Check from Claude
- GIVEN an MCP client connected to Dibs
- WHEN it calls the check tool with the candidates "Messier" and "Onoma"
- THEN it receives a report for each, with verdicts and evidence

#### Scenario: Custom endings from the client
- GIVEN an MCP client connected to Dibs
- WHEN it calls the check tool with the candidate "Dibs" and the endings .com and .dev
- THEN the domain results cover dibs.com and dibs.dev only
