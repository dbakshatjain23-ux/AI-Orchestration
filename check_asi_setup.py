"""Readiness checks only. Never prints secret values or contacts external APIs."""
import json
import os

from config import settings


def check():
    checks = {
        'dev4_integration_enabled': settings.enable_dev4_integration,
        'mock_adapter_selected': os.getenv('WORKSPACE_ADAPTER', 'mock') == 'mock',
        'legacy_google_actions_disabled': not settings.enable_google_actions,
        'real_actions_disabled': os.getenv('ENABLE_REAL_ACTIONS', 'false') != 'true',
        'asi_api_key_present': bool(settings.asi_one_api_key.strip()),
        'stable_agent_seed_present': bool(settings.agent_seed.strip()),
        'agentverse_transport_configured': bool(settings.agent_mailbox or settings.agent_endpoint
                                               or settings.agent_public_base_url),
    }
    addresses = [os.getenv(f'AGENT{i}_ADDRESS', '').strip() for i in range(1, 7)]
    try:
        from uagents_core.crypto import is_valid_address
        checks['six_distinct_valid_specialist_addresses'] = (
            len(set(addresses)) == 6 and all(is_valid_address(address) for address in addresses)
        )
    except ImportError:
        checks['six_distinct_valid_specialist_addresses'] = False
    return {'configured': all(checks.values()), 'checks': checks,
            'live_connectivity_verified': False,
            'note': 'Configuration checks do not establish Agentverse reachability, API access, or billing.'}


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['configured'] else 1)
