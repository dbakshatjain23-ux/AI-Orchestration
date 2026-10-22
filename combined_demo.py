"""Offline supervisor -> Developer 4 -> mock integration demonstration.

The scripted planner substitutes only the remote ASI API. The supervisor approval
state machine, real dataset policy, mock adapter, and persistent audit are real.
"""
import argparse
import asyncio
import json
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-id', required=True)
    parser.add_argument('--action', choices=['sheets_sync', 'gmail_draft', 'calendar_event'], default='gmail_draft')
    parser.add_argument('--start-at', default='')
    parser.add_argument('--end-at', default='')
    parser.add_argument('--decision', choices=['approve', 'deny'], required=True,
                        help='Your decision for this MOCK demo, not an authorization for real Google actions')
    args = parser.parse_args()
    os.environ.update(ENABLE_DEV4_INTEGRATION='true', WORKSPACE_ADAPTER='mock',
                      ENABLE_REAL_ACTIONS='false', ENABLE_GOOGLE_ACTIONS='false')
    from agents.supervisor_agent import SupervisorService

    arguments = {'record_id': args.record_id, 'action': args.action,
                 'start_at': args.start_at, 'end_at': args.end_at}

    class ScriptedPlanner:
        def __init__(self):
            self.calls = 0
            self.result = None

        async def stream_async(self, messages, session_id, tools=None):
            self.calls += 1
            if self.calls == 1:
                yield {'choices': [{'delta': {'tool_calls': [{
                    'id': 'combined-demo-operation', 'type': 'function',
                    'function': {'name': 'run_dev4_workspace_demo', 'arguments': json.dumps(arguments)},
                }]}}]}
            else:
                self.result = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
                yield {'choices': [{'delta': {'content': 'Offline combined demo finished; inspect the structured result.'}}]}

    async def run():
        planner = ScriptedPlanner()
        service = SupervisorService(planner=planner)
        first = await service.receive('local-demo-user', 'Run the requested mock workspace action')
        print(first.content)
        await service.receive('local-demo-user', args.decision)
        print(json.dumps({'planner': 'scripted-offline', 'result': planner.result,
                          'external_actions_executed': False}, indent=2))

    asyncio.run(run())


if __name__ == '__main__':
    main()
