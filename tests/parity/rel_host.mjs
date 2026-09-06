/** Долгоживущий хост компилятора на JS -- один процесс на всю сюиту. */
import { createInterface } from "node:readline";

import { compileQuery } from "../../libs/js/src/core/rel/domain.js";
import { compileExpr } from "../../libs/js/src/core/rel/compile.js";
import { computedColumns } from "../../libs/js/src/core/rel/fields.js";
import { evaluate } from "../../libs/js/src/core/expr.js";
import { makeModels } from "../../libs/js/src/core/runtime/fields.js";
import { развернутьТекст } from "../../libs/js/src/build/plan.mjs";

const развернуть = (что) => развернутьТекст(что);

let МОДЕЛИ = null;

//: Имена -- те же, что у питона, чтобы проверка читалась одинаково с обеих
//: сторон.
const ОПЕРАЦИИ = {
  compile_query: (payload) => compileQuery(
    JSON.stringify(развернуть(JSON.parse(payload)))),
  compile_expr: (node, opts) => {
    node = развернуть(node);
    const o = { ...(opts || {}) };
    if (Array.isArray(o.nullable)) o.nullable = new Set(o.nullable);
    const c = compileExpr(node, o);
    // `Compiled` -- объект с методами; по проводу едут только его поля.
    return { sql: c.sql, params: c.params, status: c.status, form: c.form,
             missing: c.missing, reads: c.reads };
  },
  parse_expr: (текст) => развернуть({ text: текст }),
  evaluate: (node, record, viewState) =>
    Boolean(evaluate(развернуть(node), { record: record || {}, view: viewState || {} })),
  load_models: (appDoc) => { МОДЕЛИ = makeModels(appDoc); return Object.keys(МОДЕЛИ); },
  computed_columns_of: (name, alias) => {
    if (!МОДЕЛИ) throw new Error("Модели не загружены: сперва load_models");
    const m = МОДЕЛИ[name];
    if (!m) throw new Error(`Нет модели ${name}; есть ${Object.keys(МОДЕЛИ)}`);
    return computedColumns(m, alias ?? "t", МОДЕЛИ);
  },
};

const строки = createInterface({ input: process.stdin });
for await (const строка of строки) {
  if (!строка.trim()) continue;
  let ответ;
  try {
    const { op, args } = JSON.parse(строка);
    const f = ОПЕРАЦИИ[op];
    if (!f) throw new Error(`Хост не умеет ${op}`);
    // `await` не лишний: без него асинхронная операция отдаёт обещание, а оно
    // сериализуется в `{}` -- проверка получает пустой ответ вместо настоящего
    // и сравнивает его молча.
    ответ = { ok: await f(...(args || [])) };
  } catch (err) {
    ответ = { error: { name: (err && err.name) || "Error",
                       message: String((err && err.message) || err) } };
  }
  process.stdout.write(JSON.stringify(ответ) + "\n");
}
