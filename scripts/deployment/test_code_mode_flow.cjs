// Synthetic tools only: no GitHub, Vercel, network, deployment, or router writes.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const source = fs.readFileSync(path.join(__dirname, 'code-mode-flow.js'), 'utf8')
const execute = new AsyncFunction('tools', 'plan', 'setTimeout', source)
const plan = {directory: '/workspace/.private/synthetic-flow', tools_directory: '/workspace/infra/scripts/deployment'}

test('local server continuously waits, collects and enters documentation without a model turn', async () => {
  const order = []; let polls = 0
  const tools = {
    async write_stdin({session_id, yield_time_ms}) {
      assert.equal(session_id, 13); assert.equal(yield_time_ms, 30000); order.push('poll')
      return ++polls === 1 ? {session_id: 13, output: ''}
        : {exit_code: 0, output: '{"java_exit":0,"python_exit":0}\n'}
    },
    async exec_command({cmd}) {
      order.push(cmd.includes('server-complete') ? 'collect' : 'documentation')
      return {exit_code: 0, output: JSON.stringify({state: 'LOCAL_VALIDATION_COLLECTED'}) + '\n'}
    },
  }
  const result = await execute(tools, {mode: 'server-local', directory: plan.directory, tools_directory: plan.tools_directory,
    worktree: '/workspace/server', session_id: 13})
  assert.equal(result.state, 'LOCAL_VALIDATION_COLLECTED')
  assert.deepEqual(order, ['poll', 'poll', 'collect', 'documentation'])
})

test('local server command failure never collects success or advances stage', async () => {
  const tools = {async write_stdin() {return {exit_code: 1, output: 'failed'}},
    async exec_command() {throw new Error('MUST_NOT_COLLECT')}}
  const result = await execute(tools, {mode: 'server-local', directory: plan.directory, tools_directory: plan.tools_directory,
    worktree: '/workspace/server', session_id: 13})
  assert.equal(result.state, 'LOCAL_VALIDATION_FAILED')
})


for (const pending of [true, false]) {
  test(`close preserves pending notices: ${pending}`, async () => {
    const order = []
    const tools = {
      async exec_command({cmd}) {
        if (cmd.includes('close-check')) {
          order.push('check')
          return {exit_code: 0, output: JSON.stringify({state: pending ? 'OUTPUT_NOTICE_PENDING' : 'READY_TO_FINISH'})}
        }
        assert.ok(cmd.includes(' finish ')); assert.ok(!cmd.includes('--compare'))
        order.push('finish'); return {exit_code: 0, output: '{"state":"completed"}'}
      },
      async update_goal() {order.push('goal')},
    }
    await execute(tools, {...plan, mode: 'close', event_id: 'a'.repeat(32), complete_goal: true})
    assert.deepEqual(order, pending ? ['check'] : ['check', 'goal', 'finish'])
  })
}
