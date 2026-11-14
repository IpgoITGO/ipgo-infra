// Code Mode AsyncFunction body. Read-only MCP/HTTP and private local evidence only.
const root = plan.tools_directory
if (typeof root !== 'string' || !root.startsWith('/') || /[\n\0]/.test(root)) throw new Error('TOOLS_DIRECTORY_REQUIRED')
const shell = value => "'" + String(value).replaceAll("'", "'\"'\"'") + "'"
const cli = async command => {
  let r = await tools.exec_command({cmd: command, max_output_tokens: 1600, yield_time_ms: 10000})
  let output = r.output
  while (r.session_id) {
    r = await tools.write_stdin({session_id: r.session_id, chars: '', max_output_tokens: 1600, yield_time_ms: 10000})
    output += r.output
  }
  if (r.exit_code !== 0) throw new Error('LOCAL_COMMAND_FAILED')
  return JSON.parse(output.trim().split('\n').at(-1))
}
if (!/^\/[^\n\0]+\/\.private\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(plan.directory)) throw new Error('PRIVATE_DIRECTORY_REQUIRED')
const helper = `python3 ${shell(root + '/session.py')}`
const journal = `python3 ${shell(root + '/worklog.py')}`
if (plan.mode === 'github-ci') {
  // Validated identity/job list stays in the private packet; no PR diff or logs in model output.
  return await cli(`${helper} ci-complete ${shell(plan.directory)} --plan ${shell(plan.directory + '/ci-plan.json')}`)
}
if (plan.mode === 'server-local') {
  if (!Number.isSafeInteger(plan.session_id) || plan.session_id <= 0 ||
      typeof plan.worktree !== 'string' || !plan.worktree.startsWith('/') || /[\n\0]/.test(plan.worktree)) throw new Error('INVALID_SERVER_PLAN')
  let r = {session_id: plan.session_id, output: plan.initial_output ?? ''}
  let output = r.output
  // Keep waiting inside this execution unit; no model turn between live polls.
  while (r.session_id) {
    r = await tools.write_stdin({session_id: r.session_id, chars: '', max_output_tokens: 1600, yield_time_ms: 30000})
    output += r.output
  }
  if (r.exit_code !== 0) return {state: 'LOCAL_VALIDATION_FAILED', exit_code: r.exit_code}
  const result = JSON.parse(output.trim().split('\n').at(-1))
  if (result.java_exit !== 0 || result.python_exit !== 0) throw new Error('LOCAL_TESTS_FAILED')
  const observed = new Date().toISOString()
  const facts = await cli(`${helper} server-complete ${shell(plan.directory)} --worktree ${shell(plan.worktree)} --observed-at ${shell(observed)} --java-exit 0 --python-exit 0`)
  await cli(`${journal} stage ${shell(plan.directory)} documentation`)
  return facts // Human review and final closure remain separate and measured.
}
if (plan.mode === 'close') {
  if (!/^[a-f0-9]{32}$/.test(plan.event_id)) throw new Error('INVALID_EVENT_ID')
  const status = await cli(`${helper} close-check ${shell(plan.directory)} --event-id ${shell(plan.event_id)}`)
  if (status.state !== 'READY_TO_FINISH') return status // Never ack notices or close on uncertainty.
  if (plan.complete_goal === true) await tools.update_goal({status: 'complete'})
  const comparison = plan.comparison_plan ? ` --compare ${shell(plan.comparison_plan)}` : ''
  return await cli(`${journal} finish ${shell(plan.directory)} --outcome completed --out ${shell(plan.directory + '/summary.json')}${comparison}`)
}
throw new Error('UNSUPPORTED_LOCAL_FLOW_MODE')
