/**
 * Долгоживущий хост компилятора на JS -- один процесс на всю сюиту.
 *
 * Проверки правил компилятора зовут его сотни раз. Поднимать node на каждый
 * вызов -- это ~80 мс на запуск против доли миллисекунды на саму работу:
 * сюита из трёхсот утверждений превращается в полминуты ожидания запусков.
 * Поэтому разговор построчный: строка запроса -- строка ответа, порядок
 * сохраняется тем, что читатель один.
 *
 * Отказ едет ответом, а не падением процесса: правила компилятора наполовину
 * состоят из отказов («голой ссылкой может стоять только boolean»), и проверять
 * их можно только если отказ доезжает словами.
 */
import { createInterface } from "node:readline";

import { compileQuery } from "../../libs/js/src/core/rel/domain.js";
import { compileExpr } from "../../libs/js/src/core/rel/compile.js";
import { computedColumns } from "../../libs/js/src/core/rel/fields.js";
import { evaluate } from "../../libs/js/src/core/expr.js";
import { makeModels } from "../../libs/js/src/core/runtime/fields.js";
import { развернутьТекст } from "../../libs/js/src/build/plan.mjs";

/**
 * Развернуть выражения, записанные строкой, -- ровно как это делает сборка.
 *
 * Рантайм строк не видит: до устройства доезжает дерево. Поэтому и здесь
 * строка разворачивается **на входе**, а не понимается компилятором: понимай
 * её компилятор, разбор пришлось бы возить на устройство.
 */
const развернуть = (что) => развернутьТекст(что);

//: Модели живут между запросами. Гнать их описание с каждым вызовом --
//: значит слать килобайты на каждое утверждение и, хуже, собирать их заново:
//: `makeModels` связывает модели друг с другом, и пересборка на каждый вызов
//: означала бы, что связь всякий раз новая.
let МОДЕЛИ = null;

//: Имена -- те же, что у питона, чтобы проверка читалась одинаково с обеих
//: сторон. Переименование здесь стоило бы слоя перевода в каждой проверке.
const ОПЕРАЦИИ = {
  // Строкой JSON, как её шлёт проверка. Разворот -- до компилятора: он ждёт
  // дерево, а строку разворачивает сборка, и здесь тот же порядок.
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
  //: Вычислить условие на записи -- то, чем устройство решает, рисовать ли
  //: узел. Питоновский вычислитель был вторым; правила спрашиваются у того,
  //: который правда решает.
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
    // `await` не лишний: без него асинхронная операция отдаёт обещание, а
    // оно сериализуется в `{}` -- проверка получает пустой ответ вместо
    // настоящего и сравнивает его молча. Поймано на первой же такой операции.
    ответ = { ok: await f(...(args || [])) };
  } catch (err) {
    ответ = { error: { name: (err && err.name) || "Error",
                       message: String((err && err.message) || err) } };
  }
  process.stdout.write(JSON.stringify(ответ) + "\n");
}
