// FUN_14017f910 @ 0x14017f910
// purpose-guess: oCSpawnablePool_register
// callers (1):
//   FUN_1400056b0 @ 1400056b0


/* WARNING: Removing unreachable block (ram,0x00014017fa19) */

void FUN_14017f910(void)

{
  longlong lVar1;
  longlong *plVar2;
  bool bVar3;
  undefined4 uVar4;
  undefined4 extraout_XMM0_Da;
  char *local_48;
  undefined4 local_40;
  undefined8 local_38;
  undefined8 uStack_30;
  undefined8 local_28;
  undefined8 uStack_20;
  undefined2 local_18;
  
  lVar1 = (longlong)DAT_141447368;
  if (DAT_141447368 == (longlong *)0x0) {
    if (DAT_1414142a7 == '\0') {
      DAT_14140ded0 = FUN_1404f4ef0();
      DAT_14140ded8 = FUN_1404f4ef0();
      DAT_14140dee0 = FUN_1404f4ef0();
      DAT_1414142a7 = '\x01';
    }
    uStack_30 = 0;
    local_28 = 0;
    uStack_20 = 0;
    local_38 = 0x17bbd6cf;
    local_18 = 0x100;
    lVar1 = FUN_1404f3bb0(0,&local_38);
    if (lVar1 == 0) {
      plVar2 = (longlong *)FUN_1401a6c20();
      DAT_141447368 = plVar2;
      FUN_14019e5d0();
      (**(code **)(*plVar2 + 0xd8))(plVar2,0x48,8);
      local_40 = 0x8000000f;
      *(undefined1 **)(plVar2[0x11] + 0x90) = &LAB_1401a88c0;
      local_48 = "oCSpawnablePool";
      uVar4 = (**(code **)(*plVar2 + 0x10))(plVar2,&local_48);
      *(uint *)((longlong)plVar2 + 0x2c) = *(uint *)((longlong)plVar2 + 0x2c) & 0xffffff9f;
      bVar3 = DAT_1414142a7 == '\0';
      *(undefined4 *)(plVar2 + 5) = 0x17bbd6cf;
      if (bVar3) {
        DAT_14140ded0 = FUN_1404f4ef0();
        DAT_14140ded8 = FUN_1404f4ef0();
        DAT_14140dee0 = FUN_1404f4ef0();
        DAT_1414142a7 = '\x01';
        uVar4 = extraout_XMM0_Da;
      }
      FUN_1404f3c70(uVar4,plVar2,0);
      plVar2[0x10] = (longlong)&LAB_1401b6f70;
      return;
    }
  }
  DAT_141447368 = (longlong *)lVar1;
  return;
}

