# Basic Settings NIC Selection Spec

## Overview

This document defines the behavior added to the Basic Settings screen so users can select and configure multiple wired interfaces independently.

## Scope

- Backend API: `GET /api/basic`, `POST /api/basic`
- Network configuration persistence: netplan reader/writer logic
- Frontend UI: Basic Settings interface input and interaction flow
- Unit tests for network/basic settings behavior

## Functional Requirements

### 1. Interface List and Selection

- The interface field in Basic Settings shall be a select box.
- Candidate interfaces shall be collected from system interfaces excluding loopback.
- Duplicate interface names shall be removed.
- Interface order shall be natural-sort style (for example: `eth0`, `eth1`, `eth10`).
- Wired interface labels shall follow:
  - `Ether0 (eth0)`
  - `Ether1 (eth1)`
  - Other interface types keep raw name as label.

### 2. API Response Extension (`GET /api/basic`)

- Existing `network` and `hostname` fields shall be preserved.
- Response shall include:
  - `interfaces`: list of objects with `value` and `label`
  - `selected_interface`: currently resolved target interface
- Optional query `interface=<name>` shall select the target interface for returned network data.
- If requested interface is invalid or unavailable, fallback shall use first available interface or default interface.

### 3. Frontend Behavior

- On Basic Settings load, interface options shall be populated from `interfaces`.
- Current selection shall use `selected_interface` (fallback to `network.interface`).
- When interface is changed:
  - If unsaved edits exist, confirmation dialog shall be shown.
  - If user cancels, selection shall revert to previous interface.
  - If user confirms, Basic Settings data shall be reloaded for selected interface.
- Concurrent reloads triggered by rapid selection changes shall be prevented by in-progress lock.

### 4. Network Read/Write Rules

- Netplan parser shall read per-interface entries for:
  - mode (`dhcp`/`static`)
  - ipv4 CIDR
  - default gateway
  - DNS list
- Network information returned for an interface shall merge runtime command output and netplan fallback values.
- Netplan writer shall update only the target interface while preserving existing entries for other interfaces.
- Output netplan YAML shall include all known entries sorted by interface natural order.

### 5. Input Normalization

- API apply flow shall normalize `interface` field to a valid available interface.
- Invalid or empty interface input shall not break apply flow and shall fallback safely.

## Non-Functional Requirements

- Existing single-interface behavior shall remain compatible.
- Backward compatibility shall be kept for current API consumers using existing fields.
- Error handling shall keep user-visible message behavior consistent with current UI conventions.

## Validation and Tests

Unit tests shall cover at least:

- `write_netplan` preserves existing interface blocks while updating another interface.
- `GET /api/basic` returns two wired interfaces with expected labels and selected interface.

Implemented test file:

- `tests/test_basic_network.py`

## Out of Scope

- Wi-Fi specific labeling policy changes
- IPv6 settings
- Advanced route metrics or multiple gateways per interface
