// social_icons_setup
// caller site (link va): 0x14048b4fc
// containing function: FUN_14048b4a0 @ 0x14048b4a0


/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_14048b4a0(undefined8 *param_1)

{
  longlong *plVar1;
  __uint64 *p_Var2;
  void *pvVar3;
  longlong lVar4;
  longlong lVar5;
  longlong lVar6;
  
  *param_1 = oILibrary::vftable;
  DeleteCriticalSection((LPCRITICAL_SECTION)(param_1 + 0x23));
  FUN_14046de90();
  FUN_1400c1b40(param_1 + 0x12);
  plVar1 = param_1 + 0xd;
  FUN_140503ed0(plVar1);
  if (*(int *)((longlong)param_1 + 0x74) != 0) {
    *(undefined4 *)(param_1 + 0xe) = 0;
    if (*plVar1 != 0) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0();
    }
    *plVar1 = 0;
    *(undefined4 *)((longlong)param_1 + 0x74) = 0;
  }
  plVar1 = param_1 + 10;
  FUN_140503ed0(plVar1);
  if (*(int *)((longlong)param_1 + 0x5c) != 0) {
    *(undefined4 *)(param_1 + 0xb) = 0;
    if (*plVar1 != 0) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0();
    }
    *plVar1 = 0;
    *(undefined4 *)((longlong)param_1 + 0x5c) = 0;
  }
  if ((*(int *)(param_1 + 8) != 0) && (pvVar3 = (void *)param_1[9], pvVar3 != (void *)0x0)) {
    p_Var2 = (__uint64 *)((longlong)pvVar3 + -8);
    _eh_vector_destructor_iterator_(pvVar3,0x40,*p_Var2,FUN_140511b80);
    if (p_Var2 != (__uint64 *)0x0) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0(p_Var2);
    }
  }
  DeleteCriticalSection((LPCRITICAL_SECTION)(param_1 + 3));
  lVar4 = param_1[1];
  if (lVar4 != 0) {
    lVar5 = param_1[2];
    lVar6 = lVar4;
    if (lVar5 != 0) {
      *(longlong *)(lVar5 + 8) = lVar4;
      lVar6 = DAT_1414471d0;
    }
    DAT_1414471d0 = lVar6;
    if (lVar4 != -1) {
      *(longlong *)(lVar4 + 0x10) = lVar5;
      lVar5 = _DAT_1414471d8;
    }
    _DAT_1414471d8 = lVar5;
    param_1[1] = 0;
    param_1[2] = 0;
    DAT_1414471c8 = DAT_1414471c8 + -1;
  }
  return;
}

