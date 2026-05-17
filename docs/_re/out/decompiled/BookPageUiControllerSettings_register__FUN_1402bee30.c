// FUN_1402bee30 @ 0x1402bee30
// purpose-guess: BookPageUiControllerSettings_register
// callers (4):
//   FUN_140405b80 @ 140405b80
//   FUN_1404085f0 @ 1404085f0
//   FUN_140433fd0 @ 140433fd0
//   FUN_140031b50 @ 140031b50


void FUN_1402bee30(void)

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
  
  lVar1 = (longlong)DAT_1414483c0;
  if (DAT_1414483c0 == (longlong *)0x0) {
    if (DAT_1414142a7 == '\0') {
      DAT_14140ded0 = FUN_1404f4ef0();
      DAT_14140ded8 = FUN_1404f4ef0();
      DAT_14140dee0 = FUN_1404f4ef0();
      DAT_1414142a7 = '\x01';
    }
    uStack_30 = 0;
    local_28 = 0;
    uStack_20 = 0;
    local_38 = 0x1768a9fd;
    local_18 = 0x100;
    lVar1 = FUN_1404f3bb0(0,&local_38);
    if (lVar1 == 0) {
      plVar2 = (longlong *)FUN_1401a6c20();
      DAT_1414483c0 = plVar2;
      FUN_140234cd0();
      (**(code **)(*plVar2 + 0xd8))(plVar2,0x138,8);
      local_40 = 0x8000002a;
      *(undefined1 **)(plVar2[0x11] + 0x90) = &LAB_1401a6d40;
      local_48 = "oIDtEntityCpntBookPageUiControllerSettings";
      uVar4 = (**(code **)(*plVar2 + 0x10))(plVar2,&local_48);
      *(uint *)((longlong)plVar2 + 0x2c) = *(uint *)((longlong)plVar2 + 0x2c) & 0xffffffdf;
      *(uint *)((longlong)plVar2 + 0x2c) = *(uint *)((longlong)plVar2 + 0x2c) | 0x40;
      bVar3 = DAT_1414142a7 == '\0';
      *(undefined4 *)(plVar2 + 5) = 0x1768a9fd;
      if (bVar3) {
        DAT_14140ded0 = FUN_1404f4ef0();
        DAT_14140ded8 = FUN_1404f4ef0();
        DAT_14140dee0 = FUN_1404f4ef0();
        DAT_1414142a7 = '\x01';
        uVar4 = extraout_XMM0_Da;
      }
      FUN_1404f3c70(uVar4,plVar2,&LAB_1403d5d40);
      lVar1 = DAT_141447c58;
      if (DAT_141447c58 != 0) {
        plVar2[0xc] = DAT_141447c58;
        if (*(int *)(lVar1 + 0x68) == 0) {
          *(longlong **)(lVar1 + 0x78) = plVar2;
        }
        else {
          *(longlong **)(*(longlong *)(lVar1 + 0x70) + 0x58) = plVar2;
        }
        plVar2[10] = *(longlong *)(lVar1 + 0x70);
        *(int *)(lVar1 + 0x68) = *(int *)(lVar1 + 0x68) + 1;
        *(longlong **)(lVar1 + 0x70) = plVar2;
      }
      plVar2[0x10] = (longlong)&LAB_1401b6e70;
      return;
    }
  }
  DAT_1414483c0 = (longlong *)lVar1;
  return;
}

