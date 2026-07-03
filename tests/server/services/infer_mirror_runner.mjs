/**
 * infer_mirror_runner.mjs — Node.js 子进程 runner
 *
 * 给 Python 跨端一致性测试用: 从 stdin 读一个 {order, brokerStatus} JSON,
 * 调前端 utils/format.js::inferOrderStatus, stdout 输出 status 字符串.
 *
 * 重要: 必须 import 真实的 format.js, 不能复制函数 (那样测的是"两份本地代码一致",
 *   而不是"前后端 infer 逻辑一致"). 跨端 drift 检测的有效性依赖于此.
 *
 * 用法 (Python 端):
 *   proc = subprocess.run(
 *       ['node', 'tests/server/services/infer_mirror_runner.mjs'],
 *       input=json.dumps({'order': order, 'brokerStatus': brokerStatus}),
 *       capture_output=True, text=True, cwd='<project_root>'
 *   )
 *   out = proc.stdout.strip()
 */
import { inferOrderStatus } from '../../../client/src/utils/format.js'

const chunks = []
process.stdin.on('data', (chunk) => chunks.push(chunk))
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(Buffer.concat(chunks).toString())
    const result = inferOrderStatus(input.order, input.brokerStatus)
    process.stdout.write(String(result))
  } catch (e) {
    process.stderr.write(`infer_mirror_runner error: ${e?.message || e}\n`)
    process.exit(1)
  }
})
