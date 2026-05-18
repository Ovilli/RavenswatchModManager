// tls_callback_1
// link va: 0x140c9457c
// containing function: tls_callback_1 @ 0x140c9457c (size=164)


void tls_callback_1(undefined8 param_1,int param_2)

{
  longlong lVar1;
  int *piVar2;
  int *piVar3;
  int iVar4;
  longlong *plVar5;
  
  if ((param_2 == 3) || (param_2 == 0)) {
    lVar1 = *(longlong *)((longlong)ThreadLocalStoragePointer + (ulonglong)_tls_index * 8);
    piVar3 = *(int **)(lVar1 + 0x20);
    while (piVar3 != (int *)0x0) {
      iVar4 = *piVar3 + -1;
      if (-1 < iVar4) {
        plVar5 = (longlong *)(piVar3 + ((longlong)iVar4 + 2) * 2);
        do {
          if (*plVar5 != 0) {
            (*(code *)PTR__guard_dispatch_icall_140e942b0)();
          }
          plVar5 = plVar5 + -1;
          iVar4 = iVar4 + -1;
        } while (-1 < iVar4);
      }
      piVar2 = *(int **)(piVar3 + 2);
      if (piVar2 != (int *)0x0) {
        thunk_FUN_140cbe5f0(piVar3);
      }
      *(int **)(lVar1 + 0x20) = piVar2;
      piVar3 = piVar2;
    }
  }
  return;
}

