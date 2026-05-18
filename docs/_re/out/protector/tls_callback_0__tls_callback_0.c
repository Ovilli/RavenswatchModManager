// tls_callback_0
// link va: 0x140c93e2c
// containing function: tls_callback_0 @ 0x140c93e2c (size=102)


void tls_callback_0(undefined8 param_1,int param_2)

{
  longlong lVar1;
  undefined **ppuVar2;
  
  if ((param_2 == 2) &&
     (lVar1 = *(longlong *)((longlong)ThreadLocalStoragePointer + (ulonglong)_tls_index * 8),
     *(char *)(lVar1 + 0x11) != '\x01')) {
    *(undefined1 *)(lVar1 + 0x11) = 1;
    for (ppuVar2 = &PTR_FUN_140e9d568; ppuVar2 != (undefined **)&DAT_140e9d580;
        ppuVar2 = ppuVar2 + 1) {
      if (*ppuVar2 != (undefined *)0x0) {
        (*(code *)PTR__guard_dispatch_icall_140e942b0)();
      }
    }
  }
  return;
}

