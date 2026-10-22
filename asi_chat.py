"""Interactive API-based ASI:One supervisor client; never auto-approves tools."""
import asyncio

from agents.supervisor_agent import SupervisorService
from check_asi_setup import check


async def chat():
    readiness = check()
    if not readiness['configured']:
        missing = ', '.join(name for name, ok in readiness['checks'].items() if not ok)
        raise SystemExit('Complete local configuration first: ' + missing)
    service = SupervisorService()
    print('ASI:One supervisor with Developer 4 in mock mode. Type quit to stop.')
    print('Requests use your ASI API account. No real Google actions are available.')
    while True:
        try:
            text = await asyncio.to_thread(input, 'You: ')
        except EOFError:
            return
        if text.strip().casefold() in {'quit', 'exit'}:
            return
        if not text.strip():
            continue
        try:
            run = await service.receive('local-console-user', text)
        except Exception:
            print('Request failed. Check API access, configured addresses and running agents. '
                  'No raw exception or secret values are displayed.')
            continue
        for progress in run.progress_messages:
            print(progress)
        print('Supervisor:', run.content)


if __name__ == '__main__':
    asyncio.run(chat())
