// Тот же самый вид работы, что и у питона, только на Kotlin.
//
// Собирается на сборке в обычный JavaScript, и на устройстве от JS его уже
// ничем не отличить. Именно поэтому Kotlin/JS выбран вместо Kotlin/Wasm:
// доезжает больше библиотек (56 % против 48 %) и не нужен WasmGC.

@OptIn(kotlin.js.ExperimentalJsExport::class)
@JsExport
fun сводка(кадр: dynamic): dynamic {
    val записи = кадр.records
    val всего = записи.length as Int
    var букв = 0
    var самое = ""
    for (i in 0 until всего) {
        val имя = (записи[i].name ?: "") as String
        букв += имя.length
        if (имя.length > самое.length) самое = имя
    }
    val ответ: dynamic = object {}
    ответ.строк = всего
    ответ.букв = букв
    ответ.самое_длинное = самое
    ответ.заглавными = самое.uppercase()
    return ответ
}
